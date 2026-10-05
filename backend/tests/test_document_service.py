from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FailingEmbeddingProvider, FakeEmbeddingProvider

from app.embedding.base import EmbeddingConfigError, EmbeddingError
from app.rag.loader import DocumentLoadError, UnsupportedDocumentError
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.services.document_service import DocumentService


def make_store(tmp_path: Path) -> ChromaStore:
    return ChromaStore(
        persist_dir=tmp_path / "chroma",
        collection_name="test_kb",
        embedding_signature=FakeEmbeddingProvider().signature(),
    )


def make_service(tmp_path: Path, store: ChromaStore, provider=None) -> DocumentService:
    return DocumentService(
        provider_factory=lambda: provider or FakeEmbeddingProvider(),
        store=store,
        documents_dir=tmp_path / "documents",
        chunk_size=120,
        chunk_overlap=20,
    )


async def test_ingest_list_retrieve_delete(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    service = make_service(tmp_path, store)

    info = await service.ingest(
        filename="rag.md",
        content="# RAG\n\n检索增强生成通过向量数据库检索相关文档。".encode(),
    )
    assert info.filename == "rag.md"
    assert info.title == "rag"
    assert info.chunks >= 1

    listed = await service.list_documents()
    assert [item.document_id for item in listed] == [info.document_id]
    assert listed[0].chunks == info.chunks

    retriever = Retriever(FakeEmbeddingProvider(), store, top_k=3)
    hits = await retriever.retrieve("向量数据库检索")
    assert hits
    # RetrievedDocument 是 TypedDict，按字典访问
    assert hits[0]["filename"] == "rag.md"
    assert hits[0]["chunk_id"].startswith(info.document_id)
    assert hits[0]["content"]
    assert hits[0]["score"] is not None

    assert await service.delete_document(info.document_id) is True
    assert await service.list_documents() == []
    assert store.count() == 0


async def test_ingest_rejects_unsupported_and_empty(tmp_path: Path) -> None:
    service = make_service(tmp_path, make_store(tmp_path))

    with pytest.raises(UnsupportedDocumentError):
        await service.ingest(filename="a.docx", content=b"data")
    with pytest.raises(DocumentLoadError):
        await service.ingest(filename="a.md", content=b"")


async def test_ingest_rolls_back_on_embedding_failure(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    service = make_service(tmp_path, store, provider=FailingEmbeddingProvider())

    with pytest.raises(EmbeddingError):
        await service.ingest(filename="a.md", content=b"# title\n\ncontent")

    # 回滚：既没有留下文档记录，也没有残留文件
    assert await service.list_documents() == []
    assert store.count() == 0
    assert list((tmp_path / "documents").glob("*")) == []


async def test_delete_unknown_document_returns_false(tmp_path: Path) -> None:
    service = make_service(tmp_path, make_store(tmp_path))
    assert await service.delete_document("does-not-exist") is False


async def test_dimension_mismatch_is_detected(tmp_path: Path) -> None:
    """集合非空时，用不同维度的 Embedding 模型入库应被拒绝（§12）。"""
    from fakes import FakeEmbeddingProvider

    store = make_store(tmp_path)
    await make_service(tmp_path, store).ingest(filename="a.md", content=b"# t\n\ncontent")

    smaller = FakeEmbeddingProvider(dimension=8)
    other = DocumentService(
        provider_factory=lambda: smaller,
        store=store,
        documents_dir=tmp_path / "documents",
        chunk_size=120,
        chunk_overlap=20,
    )

    with pytest.raises(EmbeddingConfigError):
        await other.ingest(filename="b.md", content=b"# t\n\ncontent")
