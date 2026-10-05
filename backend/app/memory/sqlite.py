"""SQLite 访问层（AGENTS.md §13）。

使用标准库 ``sqlite3`` + 轻量仓储，SQL 与表结构集中在这里，业务层不写 SQL。

表结构一次性定义完整（users / user_preferences / tasks / task_runs / memories），
避免后续反复迁移。注意区分：
- ``task_runs``：Agent 运行记录（应用数据）
- ``memories`` / ``user_preferences``：应用长期记忆
- LangGraph Checkpoint（短期记忆）由 langgraph-checkpoint-sqlite 单独维护，不在这里
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      TEXT PRIMARY KEY,
    display_name TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id    TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    query      TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 一个任务可以有多次运行记录（首次执行、继续生成、重新生成……）。
-- attempt_no 从 1 递增，用于「保留每次尝试」与稳定排序。
CREATE TABLE IF NOT EXISTS task_runs (
    run_id               TEXT PRIMARY KEY,
    task_id              TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    attempt_no           INTEGER NOT NULL DEFAULT 1,
    status               TEXT NOT NULL,
    retry_count          INTEGER NOT NULL DEFAULT 0,
    failed_chapters_json TEXT,
    result_json          TEXT,
    error_type           TEXT,
    started_at           TEXT NOT NULL,
    finished_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_created ON tasks(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id);

CREATE TABLE IF NOT EXISTS memories (
    memory_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT NOT NULL,
    kind           TEXT NOT NULL,
    content        TEXT NOT NULL,
    source_task_id TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS skills (
    skill_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    content     TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    builtin     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS presets (
    preset_id   TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    query       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 轻量元数据（如「默认预设是否已写入」）：让「删空预设」不会被重启后重新 seed
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# 幂等迁移：仅新增列/表，不改写既有数据（本项目首个迁移，见 AGENTS.md §13）。
# 形如 (表名, 列名, DDL)；执行前用 PRAGMA table_info 判断列是否已存在。
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "task_runs",
        "attempt_no",
        "ALTER TABLE task_runs ADD COLUMN attempt_no INTEGER NOT NULL DEFAULT 1",
    ),
)


class SqliteDatabase:
    """极简 SQLite 封装：每次操作使用独立连接（个人知识库场景足够）。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        """建库建表 + 幂等迁移。启动时调用一次；可重复执行。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)
            connection.commit()

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """按需补列（既有库升级路径；旧数据保持可用）。"""
        for table, column, ddl in MIGRATIONS:
            columns = {
                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if column not in columns:
                connection.execute(ddl)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        finally:
            connection.close()
