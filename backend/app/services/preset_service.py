"""预设任务服务。

预设是工作台的**输入快捷方式**（标题 + 说明 + 完整 query，可选绑定检索范围与
「直接运行」开关），由用户自由增删改，持久化在 SQLite。首次启动写入一组默认
预设（``data/settings`` 无关，用 ``app_meta`` 标记保证「删空后重启不复活」）。
"""

from __future__ import annotations

from app.memory.repository import PresetRecord, PresetRepository
from app.memory.sqlite import SqliteDatabase

# 默认预设是**与领域无关的任务模板**：主题由用户的知识库内容决定，预设只描述
# 「任务形态」（综述 / 对比 / 提炼 / 术语 / 摘要），因此在任何资料上都可直接使用。
# 前 6 条会显示在工作台（其余进入「更多」下拉），按「最能体现 Agent 能力」
# 的顺序排列；其中「对比分析 / 要点提炼 / 术语梳理」与内置技能
# （builtin-compare / builtin-takeaways / builtin-glossary）的触发场景对齐，
# 便于规划器自动选用对应技能。
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

# 「直接输出知识库原文」模式的两个系统预设：不绑定范围，运行时按 query 或
# 工作台当前选择自动选一篇文档。两条的差别是「全库自动选」与「限定当前范围」。
DEFAULT_VERBATIM_PRESETS: list[dict[str, str]] = [
    {
        "preset_id": "preset-verbatim-auto",
        "title": "输出知识库原文",
        "description": "自动选择与任务最相关的一篇文档，逐字输出完整原文",
        "query": (
            "从我的知识库中选择与任务最相关的一篇文档，逐字输出完整原文，"
            "不要改写、总结或省略任何段落"
        ),
        "output_mode": "verbatim",
    },
    {
        "preset_id": "preset-verbatim-scope",
        "title": "范围内原文输出",
        "description": "只在你选定的检索范围内选择一篇文档，逐字输出全文",
        "query": (
            "从当前选定的检索范围中选择最相关的一篇文档，逐字输出完整原文，"
            "不要改写、总结或省略任何段落"
        ),
        "output_mode": "verbatim",
    },
]

# 两组默认预设使用不同的 app_meta marker：新版补种原文预设时，不会因为
# 「生成内容预设早已 seed 过」而被跳过；删掉后也不会复活。
_VERBATIM_SEED_KEY = "presets_verbatim_seeded"


class PresetNotFoundError(Exception):
    """预设不存在。"""


class PresetOrderError(Exception):
    """提交的排序列表与当前预设不一致（通常是并发增删导致）。"""


class PresetService:
    """预设 CRUD 与默认预设写入。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._repository = PresetRepository(database)

    async def ensure_seeded(self) -> None:
        """首次启动写入默认预设（幂等，且删空后不会复活）。

        生成内容与原文输出两组默认预设使用独立 marker：升级到「两种模式分开」
        后，已有安装仍会补上原文预设，但不会重复补种或复活用户删掉的条目。
        """
        await self._repository.seed_once(DEFAULT_PRESETS)
        await self._repository.seed_once(DEFAULT_VERBATIM_PRESETS, key=_VERBATIM_SEED_KEY)

    async def list_presets(self, output_mode: str | None = None) -> list[PresetRecord]:
        return await self._repository.list_presets(output_mode)

    async def create_preset(
        self,
        *,
        title: str,
        description: str,
        query: str,
        category_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        auto_run: bool = False,
        output_mode: str = "generate",
    ) -> PresetRecord:
        return await self._repository.create_preset(
            title=title.strip(),
            description=description.strip(),
            query=query.strip(),
            category_ids=category_ids,
            document_ids=document_ids,
            auto_run=auto_run,
            output_mode=output_mode,
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
        output_mode: str | None = None,
    ) -> PresetRecord:
        """``category_ids=None`` 表示不修改范围；传列表则整组替换（空列表 = 清除绑定）。"""
        updated = await self._repository.update_preset(
            preset_id,
            title=title.strip() if title is not None else None,
            description=description.strip() if description is not None else None,
            query=query.strip() if query is not None else None,
            category_ids=category_ids,
            document_ids=document_ids,
            auto_run=auto_run,
            output_mode=output_mode,
        )
        if updated is None:
            raise PresetNotFoundError(f"预设不存在：{preset_id}")
        return updated

    async def delete_preset(self, preset_id: str) -> None:
        deleted = await self._repository.delete_preset(preset_id)
        if not deleted:
            raise PresetNotFoundError(f"预设不存在：{preset_id}")

    async def reorder_presets(
        self, preset_ids: list[str], *, output_mode: str = "generate"
    ) -> list[PresetRecord]:
        """按 id 列表重排**同一输出方式**内的预设；要求与当前该组集合一致。"""
        current = await self._repository.list_presets(output_mode)
        existing = {item.preset_id for item in current}
        ordered = list(dict.fromkeys(preset_ids))
        if len(ordered) != len(preset_ids) or set(ordered) != existing:
            raise PresetOrderError("预设列表已变化，请刷新后重试")
        return await self._repository.reorder_presets(ordered, output_mode=output_mode)
