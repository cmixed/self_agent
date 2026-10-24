"""技能服务。

技能是 Agent 可调用的**结构化指令模块**（做什么/怎么做的说明），不是外部
工具（§31：MVP 不做 Web 检索/代码执行类能力）。Planner 依据技能目录决定
是否使用技能，``skills`` 节点按技能指令产出结论供后续章节写作使用。

文件是唯一内容源：``<skills_dir>/<skill_id>/SKILL.md`` + 标准附件目录
（``references/`` / ``resources/`` / ``scripts/``），由
:class:`app.skills.store.SkillFileStore` 读写。SQLite 不再保存技能。

内置技能来自 ``backend/app/skill_packages/<skill_id>/``，在
``SEED_BUILTIN_SKILLS=true`` 时复制到技能目录（已存在的不覆盖），可编辑/停用，
不可删除（避免重启后被 seed 复活）。
"""

from __future__ import annotations

from pathlib import Path

from app.skills.errors import (
    BuiltinSkillProtectedError,
    SkillNameConflictError,
    SkillNotFoundError,
    SkillParseError,
    SkillResourceNameConflictError,
    SkillResourceNotFoundError,
)
from app.skills.models import SkillRecord, SkillResourceRecord
from app.skills.store import SkillFileStore

# 内置技能包目录（随代码分发，用户可读不可改）
BUILTIN_PACKAGES_DIR = Path(__file__).resolve().parents[1] / "skill_packages"
BUILTIN_SKILL_IDS = ("builtin-compare", "builtin-takeaways", "builtin-glossary")

__all__ = [
    "BUILTIN_PACKAGES_DIR",
    "BUILTIN_SKILL_IDS",
    "BuiltinSkillProtectedError",
    "SkillNameConflictError",
    "SkillNotFoundError",
    "SkillParseError",
    "SkillResourceNameConflictError",
    "SkillResourceNotFoundError",
    "SkillService",
]


class SkillService:
    """技能 CRUD 与内置技能 seed（API 层与 Agent 目录共用）。"""

    def __init__(
        self,
        store: SkillFileStore,
        *,
        builtin_packages_dir: Path | None = None,
    ) -> None:
        self._store = store
        self._builtin_packages_dir = builtin_packages_dir or BUILTIN_PACKAGES_DIR

    @property
    def store(self) -> SkillFileStore:
        return self._store

    async def ensure_seeded(self) -> None:
        """应用启动时写入内置技能（幂等：已存在的不覆盖，用户修改保留）。"""
        await self._store.ensure_root()
        await self._store.seed_from_directory(self._builtin_packages_dir)

    async def list_skills(self) -> list[SkillRecord]:
        return await self._store.list_skills()

    async def enabled_skills(self) -> list[SkillRecord]:
        """Agent 技能目录：仅启用中的技能。"""
        return await self._store.list_skills(enabled_only=True)

    async def get_skill(self, skill_id: str) -> SkillRecord:
        return await self._require_skill(skill_id)

    async def create_skill(
        self,
        *,
        name: str,
        description: str,
        content: str,
        source_filename: str | None = None,
    ) -> SkillRecord:
        return await self._store.create_skill(
            name=name.strip(),
            description=description.strip(),
            content=content.strip(),
            source_filename=source_filename.strip() if source_filename else None,
        )

    async def update_skill(
        self,
        skill_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        content: str | None = None,
        enabled: bool | None = None,
    ) -> SkillRecord:
        await self._require_skill(skill_id)
        updated = await self._store.update_skill(
            skill_id,
            name=name.strip() if name is not None else None,
            description=description.strip() if description is not None else None,
            content=content.strip() if content is not None else None,
            enabled=enabled,
        )
        if updated is None:
            raise SkillNotFoundError(f"技能不存在：{skill_id}")
        return updated

    async def delete_skill(self, skill_id: str) -> None:
        existing = await self._require_skill(skill_id)
        if existing.builtin:
            raise BuiltinSkillProtectedError("内置技能不可删除，可停用或编辑")
        if not await self._store.delete_skill(skill_id):
            raise SkillNotFoundError(f"技能不存在：{skill_id}")

    # --- 技能附件（L3）---

    async def list_resources(self, skill_id: str) -> list[SkillResourceRecord]:
        await self._require_skill(skill_id)
        return await self._store.list_resources(skill_id)

    async def resources_for_skills(
        self, skill_ids: list[str]
    ) -> dict[str, list[SkillResourceRecord]]:
        return await self._store.list_resources_for_skills(skill_ids)

    async def create_resource(
        self, skill_id: str, *, name: str, content: str
    ) -> SkillResourceRecord:
        await self._require_skill(skill_id)
        return await self._store.create_resource(
            skill_id, name=name.strip(), content=content.strip()
        )

    async def update_resource(
        self,
        skill_id: str,
        resource_id: str,
        *,
        name: str | None = None,
        content: str | None = None,
    ) -> SkillResourceRecord:
        await self._require_skill(skill_id)
        updated = await self._store.update_resource(
            skill_id,
            resource_id,
            name=name.strip() if name is not None else None,
            content=content.strip() if content is not None else None,
        )
        if updated is None:
            raise SkillResourceNotFoundError(f"附件不存在：{resource_id}")
        return updated

    async def delete_resource(self, skill_id: str, resource_id: str) -> None:
        await self._require_skill(skill_id)
        if not await self._store.delete_resource(skill_id, resource_id):
            raise SkillResourceNotFoundError(f"附件不存在：{resource_id}")

    async def _require_skill(self, skill_id: str) -> SkillRecord:
        existing = await self._store.get_skill(skill_id)
        if existing is None:
            raise SkillNotFoundError(f"技能不存在：{skill_id}")
        return existing
