from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.memory.repository import TaskRepository
from app.memory.sqlite import SqliteDatabase


@pytest.fixture
def repository(tmp_path: Path) -> TaskRepository:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    return TaskRepository(database)


async def test_schema_is_idempotent(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    database.initialize()  # 可重复执行

    with database.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"users", "user_preferences", "tasks", "task_runs", "memories"} <= tables


async def test_start_and_finish_run(repository: TaskRepository) -> None:
    await repository.start_run(task_id="t1", user_id="u1", query="写一篇综述")

    running = await repository.get_task("t1")
    assert running is not None
    assert running.status == "running"
    assert running.query == "写一篇综述"
    assert running.result is None
    assert running.finished_at is None

    await repository.finish_run(
        task_id="t1",
        result={
            "task_id": "t1",
            "status": "completed",
            "retry_count": 1,
            "failed_chapters": ["chapter_2"],
            "final_answer": "# 标题",
        },
    )

    done = await repository.get_task("t1")
    assert done is not None
    assert done.status == "completed"
    assert done.finished_at is not None
    assert done.result is not None
    assert done.result["final_answer"] == "# 标题"
    assert done.result["failed_chapters"] == ["chapter_2"]


async def test_fail_run_records_error_type(repository: TaskRepository) -> None:
    await repository.start_run(task_id="t2", user_id="u1", query="q")
    await repository.fail_run(task_id="t2", error_type="llm_response_format_error")

    record = await repository.get_task("t2")
    assert record is not None
    assert record.status == "failed"
    assert record.error_type == "llm_response_format_error"


async def test_get_unknown_task_returns_none(repository: TaskRepository) -> None:
    assert await repository.get_task("missing") is None


async def test_list_tasks_filters_by_user_and_orders(repository: TaskRepository) -> None:
    await repository.start_run(task_id="a", user_id="u1", query="first")
    await repository.start_run(task_id="b", user_id="u2", query="other user")
    await repository.start_run(task_id="c", user_id="u1", query="second")

    tasks = await repository.list_tasks(user_id="u1")
    assert [task.task_id for task in tasks] == ["c", "a"]

    assert [task.task_id for task in await repository.list_tasks(user_id="u2")] == ["b"]
    assert await repository.list_tasks(user_id="nobody") == []


async def test_list_tasks_filters_by_output_mode(repository: TaskRepository) -> None:
    await repository.start_run(task_id="gen", user_id="u1", query="写综述", output_mode="generate")
    await repository.finish_run(
        task_id="gen", result={"status": "completed", "output_mode": "generate"}
    )
    await repository.start_run(
        task_id="verbatim", user_id="u1", query="输出原文", output_mode="verbatim"
    )
    await repository.finish_run(
        task_id="verbatim", result={"status": "completed", "output_mode": "verbatim"}
    )

    generated = await repository.list_tasks(user_id="u1", output_mode="generate")
    verbatim = await repository.list_tasks(user_id="u1", output_mode="verbatim")

    assert [task.task_id for task in generated] == ["gen"]
    assert [task.task_id for task in verbatim] == ["verbatim"]
    # 不传 output_mode 时两种模式都返回（顶栏胶囊需要看到全部运行中任务）
    assert [task.task_id for task in await repository.list_tasks(user_id="u1")] == [
        "verbatim",
        "gen",
    ]


async def test_users_row_is_created(repository: TaskRepository) -> None:
    await repository.start_run(task_id="t3", user_id="new-user", query="q")

    with repository._database.connect() as connection:  # noqa: SLF001 - 测试校验建表效果
        row = connection.execute(
            "SELECT user_id FROM users WHERE user_id = ?", ("new-user",)
        ).fetchone()
    assert row is not None


async def test_migration_adds_attempt_no_to_legacy_db(tmp_path: Path) -> None:
    """旧库（无 attempt_no 列、run_id == task_id）升级后仍可用，旧行成为第 1 次尝试。"""
    legacy = tmp_path / "legacy.db"
    connection = sqlite3.connect(legacy)
    connection.executescript(
        """
        CREATE TABLE tasks (task_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                            query TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE task_runs (run_id TEXT PRIMARY KEY,
                                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                                status TEXT NOT NULL, retry_count INTEGER NOT NULL DEFAULT 0,
                                failed_chapters_json TEXT, result_json TEXT, error_type TEXT,
                                started_at TEXT NOT NULL, finished_at TEXT);
        INSERT INTO tasks VALUES ('t1','u1','旧任务','failed','2026-01-01T00:00:00+00:00');
        INSERT INTO task_runs (run_id, task_id, status, started_at, error_type)
        VALUES ('t1','t1','failed','2026-01-01T00:00:00+00:00','llm_quota_exhausted');
        """
    )
    connection.commit()
    connection.close()

    database = SqliteDatabase(legacy)
    database.initialize()
    database.initialize()  # 幂等

    repository = TaskRepository(database)
    attempts = await repository.list_attempts("t1")
    assert [(a.attempt_no, a.status, a.error_type) for a in attempts] == [
        (1, "failed", "llm_quota_exhausted")
    ]

    # 续跑在旧库上追加第 2 次尝试
    await repository.resume_run(task_id="t1")
    attempts = await repository.list_attempts("t1")
    assert [a.attempt_no for a in attempts] == [1, 2]
    record = await repository.get_task("t1")
    assert record is not None and record.status == "running"


async def test_list_tasks_projects_summary_fields_only(repository: TaskRepository) -> None:
    """列表查询只带 TaskSummary 需要的字段，不解析整份 result_json。

    长文任务的 result_json 可达 150KB+，而前端每 5 秒轮询一次列表；
    这里锁住投影行为，避免有人改回 ``SELECT result_json`` 造成静默退化。
    """
    await repository.start_run(task_id="t1", user_id="u1", query="写综述")
    await repository.finish_run(
        task_id="t1",
        result={
            "status": "completed",
            "mode": "longform",
            "retry_count": 2,
            "failed_chapters": ["chapter_2"],
            "final_answer": "# 很长的正文" * 100,
        },
    )

    [task] = await repository.list_tasks(user_id="u1")

    assert task.result is not None
    assert task.result["mode"] == "longform"
    assert task.result["retry_count"] == 2
    assert task.result["failed_chapters"] == ["chapter_2"]
    # 正文不在列表投影里（详情接口才返回）
    assert "final_answer" not in task.result
