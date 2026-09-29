"""仓储层：任务运行记录。

业务层只调用这里的异步方法，不直接写 SQL（AGENTS.md §13 / §28）。
sqlite3 是同步阻塞的，因此统一通过 ``asyncio.to_thread`` 执行，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.memory.sqlite import SqliteDatabase


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class TaskRecord:
    """一次任务及其最近一次运行的汇总。"""

    task_id: str
    user_id: str
    query: str
    status: str
    created_at: str
    finished_at: str | None
    error_type: str | None
    result: dict[str, Any] | None


class TaskRepository:
    """tasks + task_runs 的读写。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def start_run(self, *, task_id: str, user_id: str, query: str) -> None:
        await asyncio.to_thread(self._start_run, task_id, user_id, query)

    async def finish_run(self, *, task_id: str, result: dict[str, Any]) -> None:
        await asyncio.to_thread(self._finish_run, task_id, result)

    async def fail_run(self, *, task_id: str, error_type: str) -> None:
        await asyncio.to_thread(self._fail_run, task_id, error_type)

    async def get_task(self, task_id: str) -> TaskRecord | None:
        return await asyncio.to_thread(self._get_task, task_id)

    async def list_tasks(self, *, user_id: str, limit: int = 20) -> list[TaskRecord]:
        return await asyncio.to_thread(self._list_tasks, user_id, limit)

    # --- 同步实现（在线程中执行）---

    def _start_run(self, task_id: str, user_id: str, query: str) -> None:
        now = utc_now()
        with self._database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?)",
                (user_id, now),
            )
            connection.execute(
                """
                INSERT INTO tasks(task_id, user_id, query, status, created_at)
                VALUES (?, ?, ?, 'running', ?)
                ON CONFLICT(task_id) DO UPDATE SET status = 'running'
                """,
                (task_id, user_id, query, now),
            )
            connection.execute(
                """
                INSERT INTO task_runs(run_id, task_id, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (task_id, task_id, now),
            )
            connection.commit()

    def _finish_run(self, task_id: str, result: dict[str, Any]) -> None:
        now = utc_now()
        status = str(result.get("status", "completed"))
        failed_chapters = result.get("failed_chapters") or []
        with self._database.connect() as connection:
            connection.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (status, task_id))
            connection.execute(
                """
                UPDATE task_runs
                   SET status = ?, retry_count = ?, failed_chapters_json = ?,
                       result_json = ?, finished_at = ?
                 WHERE run_id = ?
                """,
                (
                    status,
                    int(result.get("retry_count", 0)),
                    json.dumps(failed_chapters, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    now,
                    task_id,
                ),
            )
            connection.commit()

    def _fail_run(self, task_id: str, error_type: str) -> None:
        now = utc_now()
        with self._database.connect() as connection:
            connection.execute("UPDATE tasks SET status = 'failed' WHERE task_id = ?", (task_id,))
            connection.execute(
                """
                UPDATE task_runs SET status = 'failed', error_type = ?, finished_at = ?
                 WHERE run_id = ?
                """,
                (error_type, now, task_id),
            )
            connection.commit()

    def _get_task(self, task_id: str) -> TaskRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT t.task_id, t.user_id, t.query, t.status, t.created_at,
                       r.finished_at, r.error_type, r.result_json
                  FROM tasks t
                  LEFT JOIN task_runs r ON r.run_id = t.task_id
                 WHERE t.task_id = ?
                """,
                (task_id,),
            ).fetchone()
        return _row_to_record(row)

    def _list_tasks(self, user_id: str, limit: int) -> list[TaskRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT t.task_id, t.user_id, t.query, t.status, t.created_at,
                       r.finished_at, r.error_type, r.result_json
                  FROM tasks t
                  LEFT JOIN task_runs r ON r.run_id = t.task_id
                 WHERE t.user_id = ?
                 ORDER BY t.created_at DESC, t.rowid DESC
                 LIMIT ?
                """,
                (user_id, max(1, limit)),
            ).fetchall()
        return [record for row in rows if (record := _row_to_record(row)) is not None]


def _row_to_record(row: Any) -> TaskRecord | None:
    if row is None:
        return None
    raw_result = row["result_json"]
    result = json.loads(raw_result) if raw_result else None
    return TaskRecord(
        task_id=row["task_id"],
        user_id=row["user_id"],
        query=row["query"],
        status=row["status"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        error_type=row["error_type"],
        result=result,
    )
