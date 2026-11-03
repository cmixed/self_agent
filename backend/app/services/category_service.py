"""知识库类别服务（多标签组织）。

文档本体在 Chroma，这里只维护「文档 ↔ 类别」的组织关系：

- 类别可自由新建 / 重命名 / 删除；删除类别只清理映射，文档保留；
- 一个文档可属于多个类别；
- 任务提交时的范围（类别 / 单文档）在这里解析成 document_id 列表，
  由 API 层「冻结」后交给 Agent，续跑沿用同一范围。
"""

from __future__ import annotations

from app.memory.repository import CategoryRecord, CategoryRepository
from app.memory.sqlite import SqliteDatabase


class CategoryNotFoundError(Exception):
    """类别不存在。"""


class CategoryNameConflictError(Exception):
    """类别名重复。"""


class CategoryService:
    """类别 CRUD、文档分类与范围解析。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._repository = CategoryRepository(database)

    async def list_categories(self) -> list[CategoryRecord]:
        return await self._repository.list_categories()

    async def create_category(self, *, name: str, description: str = "") -> CategoryRecord:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("类别名不能为空")
        if await self._repository.find_by_name(cleaned) is not None:
            raise CategoryNameConflictError(f"类别已存在：{cleaned}")
        return await self._repository.create_category(name=cleaned, description=description.strip())

    async def update_category(
        self,
        category_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> CategoryRecord:
        if name is not None:
            cleaned = name.strip()
            if not cleaned:
                raise ValueError("类别名不能为空")
            existing = await self._repository.find_by_name(cleaned)
            if existing is not None and existing.category_id != category_id:
                raise CategoryNameConflictError(f"类别已存在：{cleaned}")
            name = cleaned
        updated = await self._repository.update_category(
            category_id,
            name=name,
            description=description.strip() if description is not None else None,
        )
        if updated is None:
            raise CategoryNotFoundError(f"类别不存在：{category_id}")
        return updated

    async def delete_category(self, category_id: str) -> None:
        if not await self._repository.delete_category(category_id):
            raise CategoryNotFoundError(f"类别不存在：{category_id}")

    async def set_document_categories(self, document_id: str, category_ids: list[str]) -> list[str]:
        """整组替换某文档的类别；返回归一化后的类别 id 列表。"""
        unique = list(dict.fromkeys(category_ids))
        for category_id in unique:
            if await self._repository.get_category(category_id) is None:
                raise CategoryNotFoundError(f"类别不存在：{category_id}")
        await self._repository.set_document_categories(document_id, unique)
        return unique

    async def document_category_map(self) -> dict[str, list[str]]:
        return await self._repository.document_category_map()

    async def purge_document(self, document_id: str) -> None:
        await self._repository.purge_document(document_id)

    async def resolve_scope(self, *, category_ids: list[str], document_ids: list[str]) -> list[str]:
        return await self._repository.resolve_scope(
            category_ids=list(dict.fromkeys(category_ids)),
            document_ids=list(dict.fromkeys(document_ids)),
        )
