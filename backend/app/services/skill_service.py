"""技能服务。

技能是 Agent 可调用的**结构化指令模块**（做什么/怎么做的说明），不是外部
工具（§31：MVP 不做 Web 检索/代码执行类能力）。Planner 依据技能目录决定
是否使用技能，``skills`` 节点按技能指令产出结论供后续章节写作使用。

内置技能随应用首次启动写入（固定 id，不覆盖用户修改），可编辑/停用，
不可删除（避免重启后被 seed 复活）。
"""

from __future__ import annotations

from app.memory.repository import SkillRecord, SkillRepository
from app.memory.sqlite import SqliteDatabase
from app.prompts import load_prompt
from app.prompts.manifest import BUILTIN_SKILL_PROMPTS


def _builtin_content(skill_id: str) -> str:
    return load_prompt(BUILTIN_SKILL_PROMPTS[skill_id]).strip()


BUILTIN_SKILLS: list[dict[str, str]] = [
    {
        "skill_id": "builtin-compare",
        "name": "对比分析",
        "description": "当任务需要比较资料中的多个技术方案/方法时使用",
        "content": _builtin_content("builtin-compare"),
    },
    {
        "skill_id": "builtin-takeaways",
        "name": "要点提炼",
        "description": "当需要从大量资料中提炼核心要点时使用",
        "content": _builtin_content("builtin-takeaways"),
    },
    {
        "skill_id": "builtin-glossary",
        "name": "术语梳理",
        "description": "当资料涉及大量专业术语、需要统一口径时使用",
        "content": _builtin_content("builtin-glossary"),
    },
]


class SkillNotFoundError(Exception):
    """技能不存在。"""


class BuiltinSkillProtectedError(Exception):
    """内置技能受保护（不可删除）。"""


class SkillService:
    """技能 CRUD 与内置技能 seed（API 层与 Agent 目录共用）。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._repository = SkillRepository(database)

    async def ensure_seeded(self) -> None:
        """应用启动时写入内置技能（幂等）。"""
        await self._repository.seed_skills(BUILTIN_SKILLS)

    async def list_skills(self) -> list[SkillRecord]:
        return await self._repository.list_skills()

    async def enabled_skills(self) -> list[SkillRecord]:
        """Agent 技能目录：仅启用中的技能。"""
        return await self._repository.list_skills(enabled_only=True)

    async def create_skill(
        self,
        *,
        name: str,
        description: str,
        content: str,
        source_filename: str | None = None,
    ) -> SkillRecord:
        return await self._repository.create_skill(
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
        updated = await self._repository.update_skill(
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
        existing = await self._repository.get_skill(skill_id)
        if existing is None:
            raise SkillNotFoundError(f"技能不存在：{skill_id}")
        if existing.builtin:
            raise BuiltinSkillProtectedError("内置技能不可删除，可停用或编辑")
        await self._repository.delete_skill(skill_id)
