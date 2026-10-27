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

CREATE TABLE IF NOT EXISTS presets (
    preset_id   TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    query       TEXT NOT NULL,
    -- 绑定的检索范围（JSON：{category_ids, document_ids}；NULL = 未绑定，运行时用当前选择）
    scope_json  TEXT,
    -- 工作台点击卡片是否直接执行（1 = 跳过「填入 → 回车」；默认 0 = 只填入输入框）
    auto_run    INTEGER NOT NULL DEFAULT 0,
    -- 工作台展示顺序（越小越靠前；新建预设追加到末尾）
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 用户自定义 LLM Provider（UI 管理）。
-- api_key 允许存本地明文（单机自用），**绝不回传前端**；
-- 若 api_key_env 指向的环境变量存在，则环境变量优先（更安全）。
CREATE TABLE IF NOT EXISTS llm_providers (
    provider_id      TEXT PRIMARY KEY,
    label            TEXT NOT NULL,
    base_url         TEXT NOT NULL,
    model            TEXT NOT NULL,
    api_key          TEXT NOT NULL DEFAULT '',
    api_key_env      TEXT NOT NULL DEFAULT '',
    requires_api_key INTEGER NOT NULL DEFAULT 1,
    is_local         INTEGER NOT NULL DEFAULT 0,
    timeout_seconds  REAL NOT NULL DEFAULT 120,
    max_retries      INTEGER NOT NULL DEFAULT 2,
    -- 线路协议：openai = OpenAI 兼容 /v1；ollama = Ollama 原生 /api/chat
    flavor           TEXT NOT NULL DEFAULT 'openai',
    -- 关闭思考模式（仅 flavor=ollama 生效）
    disable_thinking INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- 知识库分类（多标签）：文档本体在 Chroma，这里只存「组织关系」。
-- category_id 外键级联：删除类别自动清理映射，文档不受影响。
CREATE TABLE IF NOT EXISTS categories (
    category_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_name ON categories(name);

CREATE TABLE IF NOT EXISTS document_categories (
    category_id TEXT NOT NULL REFERENCES categories(category_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (category_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_categories_doc ON document_categories(document_id);

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
    (
        "llm_providers",
        "flavor",
        "ALTER TABLE llm_providers ADD COLUMN flavor TEXT NOT NULL DEFAULT 'openai'",
    ),
    (
        "llm_providers",
        "disable_thinking",
        "ALTER TABLE llm_providers ADD COLUMN disable_thinking INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "presets",
        "scope_json",
        "ALTER TABLE presets ADD COLUMN scope_json TEXT",
    ),
    (
        "presets",
        "auto_run",
        "ALTER TABLE presets ADD COLUMN auto_run INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "presets",
        "sort_order",
        "ALTER TABLE presets ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
    ),
)

# 一次性回填：把明显指向 Ollama 的既有配置标成原生协议（否则它们的"关闭思考"
# 开关不会生效，因为 /v1 端点不接受 think 字段）。
_BACKFILL_OLLAMA_FLAVOR = (
    "UPDATE llm_providers SET flavor = 'ollama' WHERE flavor = 'openai' AND base_url LIKE '%11434%'"
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
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                connection.execute(ddl)
        connection.execute(_BACKFILL_OLLAMA_FLAVOR)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        finally:
            connection.close()
