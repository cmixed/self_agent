from __future__ import annotations

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


async def test_users_row_is_created(repository: TaskRepository) -> None:
    await repository.start_run(task_id="t3", user_id="new-user", query="q")

    with repository._database.connect() as connection:  # noqa: SLF001 - 测试校验建表效果
        row = connection.execute(
            "SELECT user_id FROM users WHERE user_id = ?", ("new-user",)
        ).fetchone()
    assert row is not None
