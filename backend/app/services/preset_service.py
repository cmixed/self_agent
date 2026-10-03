"""预设任务服务。

预设是工作台的**输入快捷方式**（标题 + 说明 + 完整 query），由用户自由
增删改，持久化在 SQLite。首次启动写入一组默认预设（``data/settings`` 无关，
用 ``app_meta`` 标记保证「删空后重启不复活」）。
"""

from __future__ import annotations

from app.memory.repository import PresetRecord, PresetRepository
from app.memory.sqlite import SqliteDatabase

DEFAULT_PRESETS: list[dict[str, str]] = [
    {
        "preset_id": "preset-rag-survey",
        "title": "RAG 技术综述",
        "description": "基于知识库资料撰写一篇带引用来源的技术综述",
        "query": "根据我的资料写一篇 RAG 技术综述",
    },
    {
        "preset_id": "preset-compare-report",
        "title": "技术方案对比报告",
        "description": "调研资料中的技术方案，输出对比与选型建议",
        "query": "调研我资料里的几种技术方案，输出对比报告并给出选型建议",
    },
    {
        "preset_id": "preset-study-notes",
        "title": "学习笔记",
        "description": "整理资料，生成一份带目录与来源引用的学习笔记",
        "query": "整理我的资料，生成一份带目录与来源引用的学习笔记",
    },
    {
        "preset_id": "preset-paper-review",
        "title": "论文精读报告",
        "description": "逐篇总结资料中论文的核心贡献、方法与局限",
        "query": "总结我资料里的论文，逐篇输出核心贡献、方法与局限",
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
