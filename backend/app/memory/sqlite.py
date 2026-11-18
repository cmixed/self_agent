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
-- 团队成员（方案A：单团队多成员）。username/password_hash 为团队版新增，
-- 旧库通过 MIGRATIONS 补列；旧默认用户会被升级为首个管理员。
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    display_name  TEXT,
    created_at    TEXT NOT NULL,
    username      TEXT,
    email         TEXT,
    password_hash TEXT,
    role          TEXT NOT NULL DEFAULT 'member',
    status        TEXT NOT NULL DEFAULT 'active',
    last_login_at TEXT
);

-- 登录令牌：只存 sha256 摘要，退出/改密/停用时删除
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires ON auth_tokens(expires_at);

-- 邮箱验证码重置：一账号一条，发新码即作废旧码
-- 对外接口密钥：只存 sha256 摘要；吊销后保留记录便于追溯
CREATE TABLE IF NOT EXISTS api_keys (
    key_id       TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT '',
    key_hash     TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);


CREATE TABLE IF NOT EXISTS password_reset_codes (
    user_id    TEXT PRIMARY KEY,
    code_hash  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0
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
    -- 输出方式：generate = 正常生成内容；verbatim = 直接输出知识库原文
    output_mode TEXT NOT NULL DEFAULT 'generate',
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
    -- 输出方式：generate / verbatim；两种模式的工作台预设相互独立
    output_mode TEXT NOT NULL DEFAULT 'generate',
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

-- 知识库：一等公民。文档归属到某个知识库，是否可见由「共享关系」组合决定，
-- 不再用单一的 team/private 开关（那相当于把权限写死在文档上）。
-- kind：team = 团队公共库（由管理员维护）；personal = 成员自己的库
CREATE TABLE IF NOT EXISTS knowledge_bases (
    kb_id       TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner_id    TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'personal',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_name ON knowledge_bases(name);

-- 团队分组（「一批人」）：共享的载体，而不是权限继承的层级
CREATE TABLE IF NOT EXISTS team_groups (
    group_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_groups_name ON team_groups(name);

-- 组成员：role=manager 可审批入组申请（默认由组内编辑者同意），admin 也可直接拉人
CREATE TABLE IF NOT EXISTS team_group_members (
    group_id  TEXT NOT NULL REFERENCES team_groups(group_id) ON DELETE CASCADE,
    user_id   TEXT NOT NULL,
    role      TEXT NOT NULL DEFAULT 'member',
    status    TEXT NOT NULL DEFAULT 'active',
    added_by  TEXT NOT NULL DEFAULT '',
    joined_at TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_group_members_user ON team_group_members(user_id, status);

-- 共享：组合关系的核心表。一条记录 = 「某个知识库（可限定若干文件）
-- 以某组能力授予某主体」。能力拆成 4 个独立开关（检索 / 列表 / 原文 / 编辑），
-- 多个主体命中的能力取并集（组合优于继承：不看角色层级，只看叠加了哪些能力）。
CREATE TABLE IF NOT EXISTS kb_shares (
    share_id      TEXT PRIMARY KEY,
    kb_id         TEXT NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    -- user = 指定成员；group = 分组；team = 全团队
    subject_type  TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    can_search    INTEGER NOT NULL DEFAULT 1,
    can_list      INTEGER NOT NULL DEFAULT 0,
    can_read      INTEGER NOT NULL DEFAULT 0,
    can_write     INTEGER NOT NULL DEFAULT 0,
    -- 共享的文件子集（JSON 数组）；空数组 = 整个知识库
    document_ids  TEXT NOT NULL DEFAULT '[]',
    -- pending = 成员提案待管理员审批；active = 生效；rejected = 驳回
    status        TEXT NOT NULL DEFAULT 'pending',
    requested_by  TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    decided_by    TEXT,
    decided_at    TEXT,
    decision_note TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kb_shares_kb ON kb_shares(kb_id, status);
CREATE INDEX IF NOT EXISTS idx_kb_shares_subject ON kb_shares(subject_type, subject_id, status);

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
    (
        "presets",
        "output_mode",
        "ALTER TABLE presets ADD COLUMN output_mode TEXT NOT NULL DEFAULT 'generate'",
    ),
    (
        "tasks",
        "output_mode",
        "ALTER TABLE tasks ADD COLUMN output_mode TEXT NOT NULL DEFAULT 'generate'",
    ),
    # 团队版：成员账号字段（旧库就地补列，旧数据保留）
    ("users", "username", "ALTER TABLE users ADD COLUMN username TEXT"),
    ("users", "email", "ALTER TABLE users ADD COLUMN email TEXT"),
    ("users", "password_hash", "ALTER TABLE users ADD COLUMN password_hash TEXT"),
    ("users", "role", "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member'"),
    ("users", "status", "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"),
    ("users", "last_login_at", "ALTER TABLE users ADD COLUMN last_login_at TEXT"),
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
        # 用户名唯一：必须在补列之后建（旧库此时才有该列）；NULL 允许重复
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        finally:
            connection.close()
