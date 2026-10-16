"""预设任务服务。

预设是工作台的**输入快捷方式**（标题 + 说明 + 完整 query），由用户自由
增删改，持久化在 SQLite。首次启动写入一组默认预设（``data/settings`` 无关，
用 ``app_meta`` 标记保证「删空后重启不复活」）。
"""

from __future__ import annotations

from app.memory.repository import PresetRecord, PresetRepository
from app.memory.sqlite import SqliteDatabase

# 默认预设是**与领域无关的任务模板**：主题由用户的知识库内容决定，预设只描述
# 「任务形态」（综述 / 对比 / 提炼 / 术语 / 摘要），因此在任何资料上都可直接使用。
# 前 3 条会显示在工作台，按「最能体现 Agent 能力」的顺序排列；其中「对比分析 /
# 要点提炼 / 术语梳理」与内置技能（builtin-compare / builtin-takeaways /
# builtin-glossary）的触发场景对齐，便于规划器自动选用对应技能。
DEFAULT_PRESETS: list[dict[str, str]] = [
    {
        "preset_id": "preset-survey",
        "title": "资料综述",
        "description": "归纳资料中的核心主题，写成带来源引用的综述长文",
        "query": "根据我的资料，归纳其中的核心主题，写一篇结构清晰、带引用来源的综述文章",
    },
    {
        "preset_id": "preset-compare",
        "title": "对比分析",
        "description": "对比资料中的多种方案、方法或观点，给出选择建议",
        "query": "对比我资料中涉及的多种方案、方法或观点，按关键维度整理，并给出适用条件与选择建议",
    },
    {
        "preset_id": "preset-key-points",
        "title": "要点提炼",
        "description": "提炼资料中的核心要点，按重要性整理并标注依据",
        "query": "提炼我资料中的核心要点，按重要性整理成清单，并标注每条要点的依据来源",
    },
    {
        "preset_id": "preset-glossary",
        "title": "术语梳理",
        "description": "整理资料中的关键术语与概念，统一口径",
        "query": "梳理我资料中的关键术语与概念，合并同一概念的不同叫法，输出带来源的术语说明",
    },
    {
        "preset_id": "preset-summary",
        "title": "内容摘要",
        "description": "把资料浓缩成一份结构化摘要，快速掌握全貌",
        "query": "把我资料的核心内容浓缩成一份结构化摘要，分层呈现主要结论与关键细节",
    },
]


class PresetNotFoundError(Exception):
    """预设不存在。"""


class PresetService:
    """预设 CRUD 与默认预设写入。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._repository = PresetRepository(database)

    async def ensure_seeded(self) -> None:
        """首次启动写入默认预设（幂等，且删空后不会复活）。"""
        await self._repository.seed_once(DEFAULT_PRESETS)

    async def list_presets(self) -> list[PresetRecord]:
        return await self._repository.list_presets()

    async def create_preset(self, *, title: str, description: str, query: str) -> PresetRecord:
        return await self._repository.create_preset(
            title=title.strip(), description=description.strip(), query=query.strip()
        )

    async def update_preset(
        self,
        preset_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        query: str | None = None,
    ) -> PresetRecord:
        updated = await self._repository.update_preset(
            preset_id,
            title=title.strip() if title is not None else None,
            description=description.strip() if description is not None else None,
            query=query.strip() if query is not None else None,
        )
        if updated is None:
            raise PresetNotFoundError(f"预设不存在：{preset_id}")
        return updated

    async def delete_preset(self, preset_id: str) -> None:
        deleted = await self._repository.delete_preset(preset_id)
        if not deleted:
            raise PresetNotFoundError(f"预设不存在：{preset_id}")
