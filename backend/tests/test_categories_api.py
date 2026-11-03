"""知识库类别（多标签组织）：仓储/服务/API 与删除清理。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.memory.repository import CategoryRepository
from app.memory.sqlite import SqliteDatabase
from app.services.category_service import (
    CategoryNameConflictError,
    CategoryNotFoundError,
    CategoryService,
)


@pytest.fixture
def service(tmp_path) -> CategoryService:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    return CategoryService(database)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


async def test_create_rename_and_delete_category(service: CategoryService) -> None:
    created = await service.create_category(name="RAG 专题", description="检索增强相关")
    assert created.name == "RAG 专题"
    assert created.document_count == 0

    renamed = await service.update_category(created.category_id, name="RAG 与向量检索")
    assert renamed is not None and renamed.name == "RAG 与向量检索"

    await service.delete_category(created.category_id)
    with pytest.raises(CategoryNotFoundError):
        await service.delete_category(created.category_id)


async def test_duplicate_name_is_rejected(service: CategoryService) -> None:
    await service.create_category(name="论文")
    with pytest.raises(CategoryNameConflictError):
        await service.create_category(name="论文")

    other = await service.create_category(name="笔记")
    with pytest.raises(CategoryNameConflictError):
        await service.update_category(other.category_id, name="论文")


async def test_document_belongs_to_multiple_categories(service: CategoryService) -> None:
    paper = await service.create_category(name="论文")
    rag = await service.create_category(name="RAG 专题")

    await service.set_document_categories("doc-1", [paper.category_id, rag.category_id])

    mapping = await service.document_category_map()
    assert sorted(mapping["doc-1"]) == sorted([paper.category_id, rag.category_id])
    counts = {item.name: item.document_count for item in await service.list_categories()}
    assert counts == {"论文": 1, "RAG 专题": 1}


async def test_unknown_category_is_rejected(service: CategoryService) -> None:
    with pytest.raises(CategoryNotFoundError):
        await service.set_document_categories("doc-1", ["ghost"])


async def test_resolve_scope_unions_categories_and_documents(service: CategoryService) -> None:
    paper = await service.create_category(name="论文")
    notes = await service.create_category(name="笔记")
    await service.set_document_categories("d1", [paper.category_id])
    await service.set_document_categories("d2", [paper.category_id, notes.category_id])

    resolved = await service.resolve_scope(
        category_ids=[paper.category_id], document_ids=["d3", "d1"]
    )
    assert resolved == ["d3", "d1", "d2"]  # 单文档优先保留顺序，类别文档追加去重

    assert await service.resolve_scope(category_ids=[notes.category_id], document_ids=[]) == ["d2"]
    assert await service.resolve_scope(category_ids=[], document_ids=[]) == []


async def test_deleting_category_keeps_documents_mapping_clean(service: CategoryService) -> None:
    paper = await service.create_category(name="论文")
    rag = await service.create_category(name="RAG")
    await service.set_document_categories("d1", [paper.category_id, rag.category_id])

    await service.delete_category(paper.category_id)

    mapping = await service.document_category_map()
    assert mapping["d1"] == [rag.category_id]


async def test_purge_document_removes_mapping(service: CategoryService) -> None:
    paper = await service.create_category(name="论文")
    await service.set_document_categories("d1", [paper.category_id])

    await service.purge_document("d1")

    assert await service.document_category_map() == {}
    counts = {item.name: item.document_count for item in await service.list_categories()}
    assert counts == {"论文": 0}


async def test_foreign_key_cascade_cleans_mapping(tmp_path) -> None:
    """类别删除时由外键级联清理映射（SQLite 层兜底）。"""
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    repository = CategoryRepository(database)
    category = await repository.create_category(name="临时", description="")
    await repository.set_document_categories("d1", [category.category_id])

    assert await repository.delete_category(category.category_id) is True
    assert await repository.document_category_map() == {}


# --- API ---


def test_category_crud_api(client: TestClient) -> None:
    created = client.post("/api/categories", json={"name": "论文", "description": "论文类"})
    assert created.status_code == 200
    category = created.json()
    assert category["document_count"] == 0

    duplicated = client.post("/api/categories", json={"name": "论文", "description": ""})
    assert duplicated.status_code == 409
    assert duplicated.json()["error_type"] == "category_name_conflict"

    renamed = client.put(f"/api/categories/{category['category_id']}", json={"name": "论文库"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "论文库"

    listed = client.get("/api/categories").json()
    assert [item["name"] for item in listed["categories"]] == ["论文库"]

    assert client.delete(f"/api/categories/{category['category_id']}").status_code == 200
    missing = client.delete(f"/api/categories/{category['category_id']}")
    assert missing.status_code == 404
    assert missing.json()["error_type"] == "category_not_found"


def test_set_document_categories_api(client: TestClient) -> None:
    first = client.post("/api/categories", json={"name": "A"}).json()
    second = client.post("/api/categories", json={"name": "B"}).json()

    # 没有该文档时 404（文档以 Chroma 为准）
    missing = client.put(
        "/api/documents/ghost/categories", json={"category_ids": [first["category_id"]]}
    )
    assert missing.status_code == 404

    unknown = client.put("/api/documents/ghost/categories", json={"category_ids": ["nope"]})
    assert unknown.status_code == 404
    assert second["category_id"]  # 保持引用，避免误删断言


def test_document_list_carries_category_ids(tmp_path) -> None:
    """文档列表一次性带出分类，避免前端逐文档查询（N+1）。"""
    from fakes import FakeEmbeddingProvider

    from app.api.deps import get_document_service
    from app.rag.store import ChromaStore
    from app.services.document_service import DocumentService

    app = create_app()
    store = ChromaStore(
        persist_dir=tmp_path / "chroma",
        collection_name="test_kb",
        embedding_signature=FakeEmbeddingProvider().signature(),
    )
    service = DocumentService(
        provider_factory=lambda: FakeEmbeddingProvider(),
        store=store,
        documents_dir=tmp_path / "documents",
        chunk_size=200,
        chunk_overlap=20,
    )
    app.dependency_overrides[get_document_service] = lambda: service

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/documents/upload",
            files={"file": ("rag.md", b"# RAG\n\nRAG uses retrieval.", "text/markdown")},
        )
        assert uploaded.status_code == 200
        document_id = uploaded.json()["document_id"]

        category = client.post("/api/categories", json={"name": "论文"}).json()
        assigned = client.put(
            f"/api/documents/{document_id}/categories",
            json={"category_ids": [category["category_id"]]},
        )
        assert assigned.status_code == 200
        assert assigned.json()["category_ids"] == [category["category_id"]]

        listed = client.get("/api/documents").json()["documents"]
        target = next(item for item in listed if item["document_id"] == document_id)
        assert target["category_ids"] == [category["category_id"]]

        # 删除文档会清理分类映射（类别保留、计数归零）
        assert client.delete(f"/api/documents/{document_id}").status_code == 200
        assert client.get("/api/categories").json()["categories"][0]["document_count"] == 0
