"""旧 SQLite 技能表 → 文件目录迁移。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.skills.migration import MIGRATION_MARKER, migrate_skills_from_sqlite
from app.skills.store import SkillFileStore

LEGACY_SCHEMA = """
CREATE TABLE skills (
    skill_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    content TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    builtin INTEGER NOT NULL DEFAULT 0,
    source_filename TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE skill_resources (
    resource_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _seed_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(LEGACY_SCHEMA)
    connection.execute(
        "INSERT INTO skills (skill_id, name, description, content, enabled, builtin, "
        "source_filename, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "old-skill",
            "旧技能",
            "当需要验证迁移时使用",
            "你是旧技能。",
            1,
            0,
            "guide.md",
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
        ),
    )
    connection.execute(
        "INSERT INTO skill_resources (resource_id, skill_id, name, content, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "r1",
            "old-skill",
            "checklist",
            "检查项",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()


def _tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    connection.close()
    return {str(row[0]) for row in rows}


async def test_migrates_legacy_skills_and_drops_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    _seed_legacy_database(database_path)
    store = SkillFileStore(tmp_path / "skills")

    migrated = await migrate_skills_from_sqlite(database_path, store)

    assert migrated == 1
    skill = await store.get_skill("old-skill")
    assert skill is not None
    assert skill.name == "旧技能"
    assert skill.source_filename == "guide.md"
    assert skill.builtin is False
    assert skill.enabled is True
    resources = await store.list_resources("old-skill")
    assert [item.resource_id for item in resources] == ["resources/checklist"]

    marker = store.root / MIGRATION_MARKER
    assert marker.is_file()
    # 旧表已删除（用户确认：直接迁移）
    assert "skills" not in _tables(database_path)
    assert "skill_resources" not in _tables(database_path)


async def test_migration_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    _seed_legacy_database(database_path)
    store = SkillFileStore(tmp_path / "skills")

    first = await migrate_skills_from_sqlite(database_path, store)
    # 用户手改内容后再次启动，不能覆盖
    await store.update_skill("old-skill", content="用户改过的指令")
    second = await migrate_skills_from_sqlite(database_path, store)

    assert first == 1
    assert second == 0
    skill = await store.get_skill("old-skill")
    assert skill is not None
    assert skill.content == "用户改过的指令"


async def test_new_database_is_untouched(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(LEGACY_SCHEMA)
    connection.execute("DELETE FROM skill_resources")
    connection.execute("DELETE FROM skills")
    connection.commit()
    connection.close()

    store = SkillFileStore(tmp_path / "skills")
    migrated = await migrate_skills_from_sqlite(database_path, store)

    assert migrated == 0
    # 空表也照常迁移完成并删除（避免留下无用结构）
    assert "skills" not in _tables(database_path)
