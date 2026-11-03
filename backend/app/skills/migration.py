"""旧 SQLite 技能表 → 文件目录的一次性迁移。

历史版本把技能存在 ``skills`` / ``skill_resources`` 两张表里。文件制上线后，
启动时把它们读出、写成 ``<skills_dir>/<skill_id>/SKILL.md`` 与附件，成功后
**删除旧表**（用户确认：直接迁移，不做长期双轨）。

约束：

- 幂等：``<skills_dir>/.migrated-from-sqlite`` 存在即跳过；技能目录已存在也不覆盖；
- 失败保留旧表：任何异常都会中断且不 DROP，下次启动可重试；
- 不依赖仓储层（那些类会随旧表一起删除），直接读 sqlite。
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.core.logging import get_logger
from app.skills.models import SkillPackageFile
from app.skills.store import SkillFileStore

logger = get_logger(__name__)

MIGRATION_MARKER = ".migrated-from-sqlite"
LEGACY_TABLES = ("skill_resources", "skills")


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _legacy_resources(connection: sqlite3.Connection, skill_id: str) -> list[SkillPackageFile]:
    rows = connection.execute(
        "SELECT name, content FROM skill_resources WHERE skill_id = ? ORDER BY created_at",
        (skill_id,),
    ).fetchall()
    resources: list[SkillPackageFile] = []
    for name, content in rows:
        resource_name = str(name).strip().replace("\\", "/")
        if not resource_name:
            continue
        resources.append(SkillPackageFile(name=resource_name, content=str(content)))
    return resources


def migrate_legacy_skills(database_path: Path, store: SkillFileStore) -> int:
    """把旧表里的技能写成文件；返回迁移的技能数。"""
    if not database_path.is_file():
        return 0

    marker = store.root / MIGRATION_MARKER
    if marker.exists():
        return 0

    connection = sqlite3.connect(database_path)
    try:
        tables = _table_names(connection)
        if "skills" not in tables:
            # 新库：没有旧数据，什么都不用做
            return 0

        rows = connection.execute(
            "SELECT skill_id, name, description, content, enabled, builtin, "
            "source_filename, created_at, updated_at FROM skills ORDER BY created_at"
        ).fetchall()

        migrated = 0
        for row in rows:
            (
                skill_id,
                name,
                description,
                content,
                enabled,
                builtin,
                source_filename,
                created_at,
                updated_at,
            ) = row
            skill_id = str(skill_id)
            if (store.root / skill_id / "SKILL.md").is_file():
                logger.info(
                    "技能目录已存在，跳过迁移",
                    extra={"event": "skill_migration_skip", "skill_id": skill_id},
                )
                continue
            resources = (
                _legacy_resources(connection, skill_id) if "skill_resources" in tables else []
            )
            store.create_skill_sync(
                name=str(name),
                description=str(description),
                content=str(content),
                source_filename=str(source_filename) if source_filename else None,
                skill_id=skill_id,
                enabled=bool(enabled),
                builtin=bool(builtin),
                created_at=str(created_at),
                updated_at=str(updated_at),
                resources=resources,
            )
            migrated += 1

        for table in LEGACY_TABLES:
            if table in tables:
                connection.execute(f"DROP TABLE IF EXISTS {table}")
        connection.commit()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(datetime.now(UTC).isoformat(timespec="seconds") + "\n", encoding="utf-8")
        return migrated
    finally:
        connection.close()


async def migrate_skills_from_sqlite(database_path: Path, store: SkillFileStore) -> int:
    """异步包装：迁移涉及磁盘 IO，放到线程执行。"""
    await store.ensure_root()
    return await asyncio.to_thread(migrate_legacy_skills, database_path, store)
