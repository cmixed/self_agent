"""仓储层：任务运行记录。

业务层只调用这里的异步方法，不直接写 SQL（AGENTS.md §13 / §28）。
sqlite3 是同步阻塞的，因此统一通过 ``asyncio.to_thread`` 执行，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

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


@dataclass(frozen=True)
class TaskAttempt:
    """任务的一次运行尝试（首次执行 / 继续生成 / 重新生成）。"""

    attempt_no: int
    status: str
    started_at: str
    finished_at: str | None
    error_type: str | None
    retry_count: int


@dataclass(frozen=True)
class MemoryRecord:
    """一条长期记忆。"""

    memory_id: int
    user_id: str
    kind: str
    content: str
    source_task_id: str | None
    created_at: str


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

    async def resume_run(self, *, task_id: str) -> None:
        """追加一次新的运行尝试（「继续生成」），**保留**此前的失败记录。"""
        await asyncio.to_thread(self._begin_attempt, task_id)

    async def list_attempts(self, task_id: str) -> list[TaskAttempt]:
        """该任务的全部运行尝试（按尝试号升序）。"""
        return await asyncio.to_thread(self._list_attempts, task_id)

    async def cancel_run(self, *, task_id: str) -> None:
        """标记任务为已取消（幂等：只影响仍在运行的记录）。"""
        await asyncio.to_thread(self._cancel_run, task_id)

    async def reconcile_running_tasks(self) -> int:
        """启动时把遗留的 running 记录标记为 cancelled。

        进程重启后不可能还有任务在运行；不做这一步，被中断的记录会永远显示「运行中」。
        """
        return await asyncio.to_thread(self._reconcile_running_tasks)

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
            self._insert_attempt(connection, task_id, now)
            connection.commit()

    @staticmethod
    def _insert_attempt(connection: Any, task_id: str, now: str) -> None:
        """追加一次尝试：run_id 为独立 uuid，attempt_no 递增。"""
        connection.execute(
            """
            INSERT INTO task_runs(run_id, task_id, attempt_no, status, started_at)
            VALUES (?, ?, COALESCE(
                       (SELECT MAX(attempt_no) FROM task_runs WHERE task_id = ?), 0) + 1,
                    'running', ?)
            """,
            (str(uuid4()), task_id, task_id, now),
        )

    _LATEST_RUN = (
        "(SELECT run_id FROM task_runs WHERE task_id = ? ORDER BY attempt_no DESC LIMIT 1)"
    )

    def _finish_run(self, task_id: str, result: dict[str, Any]) -> None:
        now = utc_now()
        status = str(result.get("status", "completed"))
        failed_chapters = result.get("failed_chapters") or []
        with self._database.connect() as connection:
            connection.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (status, task_id))
            connection.execute(
                f"""
                UPDATE task_runs
                   SET status = ?, retry_count = ?, failed_chapters_json = ?,
                       result_json = ?, finished_at = ?
                 WHERE run_id = {self._LATEST_RUN}
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
                f"""
                UPDATE task_runs SET status = 'failed', error_type = ?, finished_at = ?
                 WHERE run_id = {self._LATEST_RUN}
                """,
                (error_type, now, task_id),
            )
            connection.commit()

    def _begin_attempt(self, task_id: str) -> None:
        """「继续生成」：任务回到 running，并追加一条新的尝试记录。"""
        now = utc_now()
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = 'running' WHERE task_id = ?", (task_id,)
            )
            self._insert_attempt(connection, task_id, now)
            connection.commit()

    def _list_attempts(self, task_id: str) -> list[TaskAttempt]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT attempt_no, status, started_at, finished_at, error_type, retry_count
                  FROM task_runs WHERE task_id = ? ORDER BY attempt_no
                """,
                (task_id,),
            ).fetchall()
        return [
            TaskAttempt(
                attempt_no=int(row["attempt_no"]),
                status=row["status"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                error_type=row["error_type"],
                retry_count=int(row["retry_count"] or 0),
            )
            for row in rows
        ]

    def _cancel_run(self, task_id: str) -> None:
        """把仍在运行的尝试标记为已取消（幂等，不会覆盖已完成的结果）。"""
        now = utc_now()
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = 'cancelled' WHERE task_id = ? AND status = 'running'",
                (task_id,),
            )
            connection.execute(
                """
                UPDATE task_runs
                   SET status = 'cancelled', error_type = 'task_cancelled', finished_at = ?
                 WHERE task_id = ? AND finished_at IS NULL
                """,
                (now, task_id),
            )
            connection.commit()

    def _reconcile_running_tasks(self) -> int:
        now = utc_now()
        with self._database.connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = 'cancelled' WHERE status = 'running'"
            )
            count = cursor.rowcount
            connection.execute(
                """
                UPDATE task_runs
                   SET status = 'cancelled', error_type = 'interrupted', finished_at = ?
                 WHERE finished_at IS NULL
                """,
                (now,),
            )
            connection.commit()
        return int(count)

    def _get_task(self, task_id: str) -> TaskRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT t.task_id, t.user_id, t.query, t.status, t.created_at,
                       r.finished_at, r.error_type, r.result_json
                  FROM tasks t
                  LEFT JOIN task_runs r ON r.run_id = (
                       SELECT run_id FROM task_runs
                        WHERE task_id = t.task_id ORDER BY attempt_no DESC LIMIT 1)
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
                  LEFT JOIN task_runs r ON r.run_id = (
                       SELECT run_id FROM task_runs
                        WHERE task_id = t.task_id ORDER BY attempt_no DESC LIMIT 1)
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


class MemoryRepository:
    """长期记忆的读写：user_preferences（键值偏好）与 memories（自由记忆）。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def get_preferences(self, user_id: str) -> dict[str, str]:
        return await asyncio.to_thread(self._get_preferences, user_id)

    async def set_preference(self, user_id: str, key: str, value: str) -> None:
        await asyncio.to_thread(self._set_preference, user_id, key, value)

    async def delete_preference(self, user_id: str, key: str) -> bool:
        return await asyncio.to_thread(self._delete_preference, user_id, key)

    async def list_memories(self, user_id: str, *, limit: int = 50) -> list[MemoryRecord]:
        return await asyncio.to_thread(self._list_memories, user_id, limit)

    async def add_memory(
        self,
        user_id: str,
        *,
        kind: str,
        content: str,
        source_task_id: str | None = None,
    ) -> MemoryRecord | None:
        """新增记忆；内容完全重复时返回 None（不重复保存）。"""
        return await asyncio.to_thread(self._add_memory, user_id, kind, content, source_task_id)

    async def delete_memory(self, user_id: str, memory_id: int) -> bool:
        return await asyncio.to_thread(self._delete_memory, user_id, memory_id)

    # --- 同步实现 ---

    def _get_preferences(self, user_id: str) -> dict[str, str]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM user_preferences WHERE user_id = ? ORDER BY key",
                (user_id,),
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def _set_preference(self, user_id: str, key: str, value: str) -> None:
        now = utc_now()
        with self._database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?)",
                (user_id, now),
            )
            connection.execute(
                """
                INSERT INTO user_preferences(user_id, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value,
                                                        updated_at = excluded.updated_at
                """,
                (user_id, key, value, now),
            )
            connection.commit()

    def _delete_preference(self, user_id: str, key: str) -> bool:
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM user_preferences WHERE user_id = ? AND key = ?",
                (user_id, key),
            )
            connection.commit()
        return cursor.rowcount > 0

    def _list_memories(self, user_id: str, limit: int) -> list[MemoryRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT memory_id, user_id, kind, content, source_task_id, created_at
                  FROM memories WHERE user_id = ?
                 ORDER BY memory_id DESC LIMIT ?
                """,
                (user_id, max(1, limit)),
            ).fetchall()
        return [
            MemoryRecord(
                memory_id=row["memory_id"],
                user_id=row["user_id"],
                kind=row["kind"],
                content=row["content"],
                source_task_id=row["source_task_id"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _add_memory(
        self, user_id: str, kind: str, content: str, source_task_id: str | None
    ) -> MemoryRecord | None:
        now = utc_now()
        with self._database.connect() as connection:
            duplicate = connection.execute(
                """
                SELECT memory_id FROM memories
                 WHERE user_id = ? AND kind = ? AND content = ?
                 LIMIT 1
                """,
                (user_id, kind, content),
            ).fetchone()
            if duplicate is not None:
                return None

            connection.execute(
                "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?)",
                (user_id, now),
            )
            cursor = connection.execute(
                """
                INSERT INTO memories(user_id, kind, content, source_task_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, kind, content, source_task_id, now),
            )
            connection.commit()
            memory_id = int(cursor.lastrowid or 0)

        return MemoryRecord(
            memory_id=memory_id,
            user_id=user_id,
            kind=kind,
            content=content,
            source_task_id=source_task_id,
            created_at=now,
        )

    def _delete_memory(self, user_id: str, memory_id: int) -> bool:
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE user_id = ? AND memory_id = ?",
                (user_id, memory_id),
            )
            connection.commit()
        return cursor.rowcount > 0


@dataclass(frozen=True)
class SkillRecord:
    """一个 Agent 可调用的技能（结构化指令模块）。"""

    skill_id: str
    name: str
    description: str
    content: str
    enabled: bool
    builtin: bool
    created_at: str
    updated_at: str
    # 由文档生成时的来源文件名（手写/内置为 None）
    source_filename: str | None = None


class SkillRepository:
    """skills 表的读写（Agent 技能，业务层不写 SQL）。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def list_skills(self, *, enabled_only: bool = False) -> list[SkillRecord]:
        return await asyncio.to_thread(self._list_skills, enabled_only)

    async def get_skill(self, skill_id: str) -> SkillRecord | None:
        return await asyncio.to_thread(self._get_skill, skill_id)

    async def create_skill(
        self, *, name: str, description: str, content: str, source_filename: str | None = None
    ) -> SkillRecord:
        return await asyncio.to_thread(
            self._create_skill, name, description, content, source_filename
        )

    async def update_skill(
        self,
        skill_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        content: str | None = None,
        enabled: bool | None = None,
    ) -> SkillRecord | None:
        return await asyncio.to_thread(
            self._update_skill, skill_id, name, description, content, enabled
        )

    async def delete_skill(self, skill_id: str) -> bool:
        return await asyncio.to_thread(self._delete_skill, skill_id)

    async def seed_skills(self, seeds: list[dict[str, str]]) -> None:
        """按固定 skill_id 写入内置技能；已存在（含被用户编辑过）的不覆盖。"""
        await asyncio.to_thread(self._seed_skills, seeds)

    # --- 同步实现（在线程中执行）---

    _SELECT = """
        SELECT skill_id, name, description, content, enabled, builtin, source_filename,
               created_at, updated_at
          FROM skills
    """

    @staticmethod
    def _record(row: Any) -> SkillRecord:
        return SkillRecord(
            skill_id=row["skill_id"],
            name=row["name"],
            description=row["description"],
            content=row["content"],
            enabled=bool(row["enabled"]),
            builtin=bool(row["builtin"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            source_filename=row["source_filename"],
        )

    def _list_skills(self, enabled_only: bool) -> list[SkillRecord]:
        query = self._SELECT
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at"
        with self._database.connect() as connection:
            rows = connection.execute(query).fetchall()
        return [self._record(row) for row in rows]

    def _get_skill(self, skill_id: str) -> SkillRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                self._SELECT + " WHERE skill_id = ?", (skill_id,)
            ).fetchone()
        return self._record(row) if row is not None else None

    def _create_skill(
        self, name: str, description: str, content: str, source_filename: str | None = None
    ) -> SkillRecord:
        now = utc_now()
        skill_id = str(uuid4())
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO skills(skill_id, name, description, content,
                                   enabled, builtin, source_filename, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?)
                """,
                (skill_id, name, description, content, source_filename, now, now),
            )
            connection.commit()
        return SkillRecord(
            skill_id=skill_id,
            name=name,
            description=description,
            content=content,
            enabled=True,
            builtin=False,
            created_at=now,
            updated_at=now,
            source_filename=source_filename,
        )

    def _update_skill(
        self,
        skill_id: str,
        name: str | None,
        description: str | None,
        content: str | None,
        enabled: bool | None,
    ) -> SkillRecord | None:
        assignments: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("name", name),
            ("description", description),
            ("content", content),
            ("enabled", enabled),
        ):
            if value is not None:
                assignments.append(f"{column} = ?")
                params.append(int(value) if isinstance(value, bool) else value)
        if not assignments:
            return self._get_skill(skill_id)

        now = utc_now()
        with self._database.connect() as connection:
            cursor = connection.execute(
                f"UPDATE skills SET {', '.join(assignments)}, updated_at = ? WHERE skill_id = ?",
                (*params, now, skill_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                self._SELECT + " WHERE skill_id = ?", (skill_id,)
            ).fetchone()
        return self._record(row) if row is not None else None

    def _delete_skill(self, skill_id: str) -> bool:
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM skills WHERE skill_id = ? AND builtin = 0", (skill_id,)
            )
            connection.commit()
        return cursor.rowcount > 0

    def _seed_skills(self, seeds: list[dict[str, str]]) -> None:
        now = utc_now()
        with self._database.connect() as connection:
            for seed in seeds:
                connection.execute(
                    """
                    INSERT INTO skills(skill_id, name, description, content,
                                       enabled, builtin, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, 1, ?, ?)
                    ON CONFLICT(skill_id) DO NOTHING
                    """,
                    (
                        seed["skill_id"],
                        seed["name"],
                        seed["description"],
                        seed["content"],
                        now,
                        now,
                    ),
                )
            connection.commit()


@dataclass(frozen=True)
class ProviderRecord:
    """用户自定义 LLM Provider（``api_key`` 明文仅存在于服务端）。"""

    provider_id: str
    label: str
    base_url: str
    model: str
    api_key: str
    api_key_env: str
    requires_api_key: bool
    is_local: bool
    timeout_seconds: float
    max_retries: int
    flavor: str
    disable_thinking: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CategoryRecord:
    """知识库类别（多标签）。"""

    category_id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    document_count: int = 0


@dataclass(frozen=True)
class PresetRecord:
    """一条预设任务（工作台的输入快捷方式，可由用户增删改）。"""

    preset_id: str
    title: str
    description: str
    query: str
    created_at: str
    updated_at: str
    # 绑定的检索范围（与 TaskScope 同构；两者皆空 = 未绑定）
    category_ids: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    # 点击卡片是否直接运行（默认 False = 仅填入输入框待确认）
    auto_run: bool = False


def _encode_scope(category_ids: list[str], document_ids: list[str]) -> str | None:
    """把范围编码为 scope_json；两者皆空时返回 None（未绑定）。"""
    if not category_ids and not document_ids:
        return None
    return json.dumps(
        {"category_ids": list(category_ids), "document_ids": list(document_ids)},
        ensure_ascii=False,
    )


def _decode_scope(raw: str | None) -> tuple[list[str], list[str]]:
    """从 scope_json 解析范围；解析失败视为未绑定（旧库/脏数据保持可用）。"""
    if not raw:
        return [], []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return [], []
    if not isinstance(data, dict):
        return [], []
    categories = [str(item) for item in (data.get("category_ids") or [])]
    documents = [str(item) for item in (data.get("document_ids") or [])]
    return categories, documents


class ProviderRepository:
    """llm_providers 的读写（自定义 Provider 配置）。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def list_providers(self) -> list[ProviderRecord]:
        return await asyncio.to_thread(self._list_providers)

    def list_providers_sync(self) -> list[ProviderRecord]:
        """同步读取：供进程启动时装载内存注册表（§28 允许 core 之外的显式同步入口）。"""
        return self._list_providers()

    async def get_provider(self, provider_id: str) -> ProviderRecord | None:
        return await asyncio.to_thread(self._get_provider, provider_id)

    async def create_provider(
        self,
        *,
        provider_id: str,
        label: str,
        base_url: str,
        model: str,
        api_key: str = "",
        api_key_env: str = "",
        requires_api_key: bool = True,
        is_local: bool = False,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        flavor: str = "openai",
        disable_thinking: bool = False,
    ) -> ProviderRecord:
        return await asyncio.to_thread(
            self._create_provider,
            provider_id,
            label,
            base_url,
            model,
            api_key,
            api_key_env,
            requires_api_key,
            is_local,
            timeout_seconds,
            max_retries,
            flavor,
            disable_thinking,
        )

    async def update_provider(self, provider_id: str, **fields: Any) -> ProviderRecord | None:
        return await asyncio.to_thread(self._update_provider, provider_id, fields)

    async def delete_provider(self, provider_id: str) -> bool:
        return await asyncio.to_thread(self._delete_provider, provider_id)

    # --- 同步实现 ---

    @staticmethod
    def _record(row: Any) -> ProviderRecord:
        return ProviderRecord(
            provider_id=row["provider_id"],
            label=row["label"],
            base_url=row["base_url"],
            model=row["model"],
            api_key=row["api_key"] or "",
            api_key_env=row["api_key_env"] or "",
            requires_api_key=bool(row["requires_api_key"]),
            is_local=bool(row["is_local"]),
            timeout_seconds=float(row["timeout_seconds"]),
            max_retries=int(row["max_retries"]),
            flavor=(row["flavor"] or "openai") if "flavor" in row.keys() else "openai",
            disable_thinking=bool(row["disable_thinking"])
            if "disable_thinking" in row.keys()
            else False,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _list_providers(self) -> list[ProviderRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM llm_providers ORDER BY created_at"
            ).fetchall()
        return [self._record(row) for row in rows]

    def _get_provider(self, provider_id: str) -> ProviderRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM llm_providers WHERE provider_id = ?", (provider_id,)
            ).fetchone()
        return self._record(row) if row is not None else None

    def _create_provider(  # noqa: PLR0913 - 与表结构一一对应的显式参数
        self,
        provider_id: str,
        label: str,
        base_url: str,
        model: str,
        api_key: str,
        api_key_env: str,
        requires_api_key: bool,
        is_local: bool,
        timeout_seconds: float,
        max_retries: int,
        flavor: str,
        disable_thinking: bool,
    ) -> ProviderRecord:
        now = utc_now()
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO llm_providers(
                    provider_id, label, base_url, model, api_key, api_key_env,
                    requires_api_key, is_local, timeout_seconds, max_retries,
                    flavor, disable_thinking, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider_id, label, base_url, model, api_key, api_key_env,
                    int(requires_api_key), int(is_local), timeout_seconds, max_retries,
                    flavor, int(disable_thinking), now, now,
                ),
            )
            connection.commit()
        record = self._get_provider(provider_id)
        assert record is not None
        return record

    def _update_provider(self, provider_id: str, fields: dict[str, Any]) -> ProviderRecord | None:
        allowed = {
            "label", "base_url", "model", "api_key", "api_key_env",
            "requires_api_key", "is_local", "timeout_seconds", "max_retries",
            "flavor", "disable_thinking",
        }
        assignments = [f"{key} = ?" for key in fields if key in allowed]
        params = [fields[key] for key in fields if key in allowed]
        if not assignments:
            return self._get_provider(provider_id)

        with self._database.connect() as connection:
            cursor = connection.execute(
                f"UPDATE llm_providers SET {', '.join(assignments)}, updated_at = ? "
                "WHERE provider_id = ?",
                (*params, utc_now(), provider_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
        return self._get_provider(provider_id)

    def _delete_provider(self, provider_id: str) -> bool:
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM llm_providers WHERE provider_id = ?", (provider_id,)
            )
            connection.commit()
        return cursor.rowcount > 0


class CategoryRepository:
    """categories / document_categories 的读写（组织关系，不含文档本体）。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def list_categories(self) -> list[CategoryRecord]:
        return await asyncio.to_thread(self._list_categories)

    async def get_category(self, category_id: str) -> CategoryRecord | None:
        return await asyncio.to_thread(self._get_category, category_id)

    async def find_by_name(self, name: str) -> CategoryRecord | None:
        return await asyncio.to_thread(self._find_by_name, name)

    async def create_category(self, *, name: str, description: str) -> CategoryRecord:
        return await asyncio.to_thread(self._create_category, name, description)

    async def update_category(
        self, category_id: str, *, name: str | None = None, description: str | None = None
    ) -> CategoryRecord | None:
        return await asyncio.to_thread(self._update_category, category_id, name, description)

    async def delete_category(self, category_id: str) -> bool:
        return await asyncio.to_thread(self._delete_category, category_id)

    async def set_document_categories(self, document_id: str, category_ids: list[str]) -> None:
        await asyncio.to_thread(self._set_document_categories, document_id, category_ids)

    async def document_category_map(self) -> dict[str, list[str]]:
        """``document_id -> [category_id]``（供文档列表一次性带出分类，避免 N+1）。"""
        return await asyncio.to_thread(self._document_category_map)

    async def purge_document(self, document_id: str) -> None:
        """删除文档时清理其分类映射（类别本身保留）。"""
        await asyncio.to_thread(self._purge_document, document_id)

    async def resolve_scope(
        self, *, category_ids: list[str], document_ids: list[str]
    ) -> list[str]:
        """把「类别 + 单文档」选择解析为去重后的 document_id 列表。"""
        return await asyncio.to_thread(self._resolve_scope, category_ids, document_ids)

    # --- 同步实现 ---

    @staticmethod
    def _record(row: Any) -> CategoryRecord:
        return CategoryRecord(
            category_id=row["category_id"],
            name=row["name"],
            description=row["description"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            document_count=int(row["document_count"]) if "document_count" in row.keys() else 0,
        )

    def _list_categories(self) -> list[CategoryRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.category_id, c.name, c.description, c.created_at, c.updated_at,
                       COUNT(m.document_id) AS document_count
                  FROM categories c
                  LEFT JOIN document_categories m ON m.category_id = c.category_id
                 GROUP BY c.category_id
                 ORDER BY c.name
                """
            ).fetchall()
        return [self._record(row) for row in rows]

    def _get_category(self, category_id: str) -> CategoryRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT c.category_id, c.name, c.description, c.created_at, c.updated_at,
                       COUNT(m.document_id) AS document_count
                  FROM categories c
                  LEFT JOIN document_categories m ON m.category_id = c.category_id
                 WHERE c.category_id = ?
                 GROUP BY c.category_id
                """,
                (category_id,),
            ).fetchone()
        return self._record(row) if row is not None else None

    def _find_by_name(self, name: str) -> CategoryRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT category_id FROM categories WHERE name = ?", (name,)
            ).fetchone()
        return self._get_category(row["category_id"]) if row is not None else None

    def _create_category(self, name: str, description: str) -> CategoryRecord:
        now = utc_now()
        category_id = str(uuid4())
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO categories(category_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (category_id, name, description, now, now),
            )
            connection.commit()
        return CategoryRecord(
            category_id=category_id,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
            document_count=0,
        )

    def _update_category(
        self, category_id: str, name: str | None, description: str | None
    ) -> CategoryRecord | None:
        assignments: list[str] = []
        params: list[Any] = []
        for column, value in (("name", name), ("description", description)):
            if value is not None:
                assignments.append(f"{column} = ?")
                params.append(value)
        if not assignments:
            return self._get_category(category_id)

        now = utc_now()
        with self._database.connect() as connection:
            cursor = connection.execute(
                f"UPDATE categories SET {', '.join(assignments)}, updated_at = ? "
                "WHERE category_id = ?",
                (*params, now, category_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
        return self._get_category(category_id)

    def _delete_category(self, category_id: str) -> bool:
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM categories WHERE category_id = ?", (category_id,)
            )
            connection.commit()
        return cursor.rowcount > 0

    def _set_document_categories(self, document_id: str, category_ids: list[str]) -> None:
        now = utc_now()
        with self._database.connect() as connection:
            connection.execute(
                "DELETE FROM document_categories WHERE document_id = ?", (document_id,)
            )
            for category_id in dict.fromkeys(category_ids):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO document_categories(category_id, document_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (category_id, document_id, now),
                )
            connection.commit()

    def _document_category_map(self) -> dict[str, list[str]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT document_id, category_id FROM document_categories"
            ).fetchall()
        mapping: dict[str, list[str]] = {}
        for row in rows:
            mapping.setdefault(row["document_id"], []).append(row["category_id"])
        return mapping

    def _purge_document(self, document_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "DELETE FROM document_categories WHERE document_id = ?", (document_id,)
            )
            connection.commit()

    def _resolve_scope(self, category_ids: list[str], document_ids: list[str]) -> list[str]:
        resolved: list[str] = list(dict.fromkeys(document_ids))
        if category_ids:
            placeholders = ",".join("?" for _ in category_ids)
            with self._database.connect() as connection:
                rows = connection.execute(
                    f"SELECT DISTINCT document_id FROM document_categories "
                    f"WHERE category_id IN ({placeholders})",
                    tuple(category_ids),
                ).fetchall()
            for row in rows:
                if row["document_id"] not in resolved:
                    resolved.append(row["document_id"])
        return resolved


class PresetRepository:
    """presets 表的读写。"""

    _PRESETS_KEY = "presets_seeded"
    _SELECT = """
        SELECT preset_id, title, description, query, scope_json, auto_run,
               created_at, updated_at
          FROM presets
    """

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def list_presets(self) -> list[PresetRecord]:
        return await asyncio.to_thread(self._list_presets)

    async def get_preset(self, preset_id: str) -> PresetRecord | None:
        return await asyncio.to_thread(self._get_preset, preset_id)

    async def create_preset(
        self,
        *,
        title: str,
        description: str,
        query: str,
        category_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        auto_run: bool = False,
    ) -> PresetRecord:
        return await asyncio.to_thread(
            self._create_preset,
            title,
            description,
            query,
            list(category_ids or []),
            list(document_ids or []),
            auto_run,
        )

    async def update_preset(
        self,
        preset_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        query: str | None = None,
        category_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        auto_run: bool | None = None,
    ) -> PresetRecord | None:
        """更新预设。``category_ids=None`` 表示**不修改**范围；传列表（含空列表）则整组替换。"""
        return await asyncio.to_thread(
            self._update_preset,
            preset_id,
            title,
            description,
            query,
            category_ids,
            document_ids,
            auto_run,
        )

    async def delete_preset(self, preset_id: str) -> bool:
        return await asyncio.to_thread(self._delete_preset, preset_id)

    async def seed_once(self, seeds: list[dict[str, str]]) -> bool:
        """仅在「从未写入过默认预设」时写入；返回是否真的写入了。

        用 ``app_meta`` 标记而非「表是否为空」判断，因此用户删掉预设（甚至删空）
        后重启不会被默认预设复活。
        """
        return await asyncio.to_thread(self._seed_once, seeds)

    # --- 同步实现（在线程中执行）---

    @staticmethod
    def _record(row: Any) -> PresetRecord:
        category_ids, document_ids = _decode_scope(row["scope_json"])
        return PresetRecord(
            preset_id=row["preset_id"],
            title=row["title"],
            description=row["description"],
            query=row["query"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            category_ids=category_ids,
            document_ids=document_ids,
            auto_run=bool(row["auto_run"]),
        )

    def _list_presets(self) -> list[PresetRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(self._SELECT + " ORDER BY created_at").fetchall()
        return [self._record(row) for row in rows]

    def _get_preset(self, preset_id: str) -> PresetRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                self._SELECT + " WHERE preset_id = ?", (preset_id,)
            ).fetchone()
        return self._record(row) if row is not None else None

    def _create_preset(
        self,
        title: str,
        description: str,
        query: str,
        category_ids: list[str],
        document_ids: list[str],
        auto_run: bool,
    ) -> PresetRecord:
        now = utc_now()
        preset_id = str(uuid4())
        scope_json = _encode_scope(category_ids, document_ids)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO presets(preset_id, title, description, query, scope_json,
                                    auto_run, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (preset_id, title, description, query, scope_json, int(auto_run), now, now),
            )
            connection.commit()
        return PresetRecord(
            preset_id=preset_id,
            title=title,
            description=description,
            query=query,
            created_at=now,
            updated_at=now,
            category_ids=list(category_ids),
            document_ids=list(document_ids),
            auto_run=auto_run,
        )

    def _update_preset(
        self,
        preset_id: str,
        title: str | None,
        description: str | None,
        query: str | None,
        category_ids: list[str] | None,
        document_ids: list[str] | None,
        auto_run: bool | None,
    ) -> PresetRecord | None:
        assignments: list[str] = []
        params: list[Any] = []
        for column, value in (("title", title), ("description", description), ("query", query)):
            if value is not None:
                assignments.append(f"{column} = ?")
                params.append(value)
        # 范围：None = 不修改；传列表（含空）= 整组替换（空表示清除绑定）
        if category_ids is not None:
            assignments.append("scope_json = ?")
            params.append(_encode_scope(list(category_ids), list(document_ids or [])))
        if auto_run is not None:
            assignments.append("auto_run = ?")
            params.append(int(auto_run))
        if not assignments:
            return self._get_preset(preset_id)

        now = utc_now()
        with self._database.connect() as connection:
            cursor = connection.execute(
                f"UPDATE presets SET {', '.join(assignments)}, updated_at = ? WHERE preset_id = ?",
                (*params, now, preset_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                self._SELECT + " WHERE preset_id = ?", (preset_id,)
            ).fetchone()
        return self._record(row) if row is not None else None

    def _delete_preset(self, preset_id: str) -> bool:
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM presets WHERE preset_id = ?", (preset_id,)
            )
            connection.commit()
        return cursor.rowcount > 0

    def _seed_once(self, seeds: list[dict[str, str]]) -> bool:
        now = utc_now()
        with self._database.connect() as connection:
            seeded = connection.execute(
                "SELECT value FROM app_meta WHERE key = ?", (self._PRESETS_KEY,)
            ).fetchone()
            if seeded is not None:
                return False
            for seed in seeds:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO presets(preset_id, title, description, query,
                                                  created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seed["preset_id"],
                        seed["title"],
                        seed["description"],
                        seed["query"],
                        now,
                        now,
                    ),
                )
            connection.execute(
                "INSERT OR REPLACE INTO app_meta(key, value) VALUES (?, ?)",
                (self._PRESETS_KEY, "1"),
            )
            connection.commit()
        return True
