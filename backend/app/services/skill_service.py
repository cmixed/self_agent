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

BUILTIN_SKILLS: list[dict[str, str]] = [
    {
        "skill_id": "builtin-compare",
        "name": "对比分析",
        "description": "当任务需要比较资料中的多个技术方案/方法时使用",
        "content": (
            "你是技术对比分析专家。请基于给定的资料，对任务中涉及的多个对象"
            "（技术/方法/工具）进行结构化对比：\n"
            "1. 先列出参与对比的对象与来源；\n"
            "2. 选择 3-6 个关键维度（如原理、性能、成本、适用场景）；\n"
            "3. 逐维度对比，每条结论注明依据来自哪份资料；\n"
            "4. 最后给出结论：各对象的适用条件与选择建议。\n"
            "资料中不存在的信息不得编造；资料不足时明确指出缺口。"
        ),
    },
    {
        "skill_id": "builtin-takeaways",
        "name": "要点提炼",
        "description": "当需要从大量资料中提炼核心要点时使用",
        "content": (
            "你是资料要点提炼专家。请基于给定的资料，围绕任务目标提炼要点：\n"
            "1. 核心结论层：3-5 条最关键的结论，每条一句话；\n"
            "2. 关键细节层：支撑每条结论的关键事实、数据或方法；\n"
            "3. 逐条标注信息来自哪份资料；\n"
            "4. 与任务目标无关的内容一律舍弃。\n"
            "只做提炼与归纳，不新增资料之外的推断。"
        ),
    },
    {
        "skill_id": "builtin-glossary",
        "name": "术语梳理",
        "description": "当资料涉及大量专业术语、需要统一口径时使用",
        "content": (
            "你是术语整理专家。请基于给定的资料，梳理任务涉及的专业术语：\n"
            "1. 以表格形式输出：术语 | 定义（基于资料） | 在本任务语境中的含义；\n"
            "2. 同一概念在不同资料中的不同叫法要合并并说明；\n"
            "3. 资料中未给出定义的术语标注「资料中未定义」；\n"
            "4. 按重要性排序，最多 15 条。"
        ),
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
