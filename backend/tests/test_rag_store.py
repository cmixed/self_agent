"""ChromaStore 的「文档列表缓存」：命中缓存、写入/删除后失效、返回副本。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.rag.store import ChromaStore


class FakeCollection:
    """只实现缓存相关路径用到的方法，并统计 ``get`` 次数。"""

    def __init__(self) -> None:
        self.metadatas: list[dict[str, Any]] = []
        self.get_calls = 0

    def count(self) -> int:
        return len(self.metadatas)

    def get(
        self,
        *,
        include: list[str] | None = None,
        where: dict[str, Any] | None = None,
        **_: Any,
    ):
        self.get_calls += 1
        if where and "document_id" in where:
            return {
                "metadatas": [
                    meta
                    for meta in self.metadatas
                    if meta.get("document_id") == where["document_id"]
                ]
            }
        return {"metadatas": list(self.metadatas)}

    def add(self, *, ids, documents, metadatas, embeddings) -> None:  # noqa: ANN001 - 贴合 chroma 签名
        self.metadatas.extend(dict(meta) for meta in metadatas)

    def delete(self, *, where: dict[str, Any]) -> None:  # noqa: ANN001
        doc_id = where.get("document_id")
        self.metadatas = [meta for meta in self.metadatas if meta.get("document_id") != doc_id]


def make_store(tmp_path: Path) -> tuple[ChromaStore, FakeCollection]:
    store = ChromaStore(
        persist_dir=tmp_path / "chroma",
        collection_name="cache_test",
        embedding_signature={},
    )
    fake = FakeCollection()
    store._collection = fake  # type: ignore[assignment]  # 只测缓存逻辑，不碰真实索引
    return store, fake


async def test_list_documents_is_cached_and_returns_copies(tmp_path: Path) -> None:
    store, fake = make_store(tmp_path)
    fake.metadatas = [
        {"document_id": "a", "filename": "a.md", "title": "A"},
        {"document_id": "a", "filename": "a.md", "title": "A"},
    ]

    first = await store.alist_documents()
    second = await store.alist_documents()

    assert [item["document_id"] for item in first] == ["a"]
    assert first[0]["chunks"] == 2
    assert fake.get_calls == 1, "第二次读取应命中缓存，不再全量扫描元数据"
    assert second == first

    # 调用方改动返回结果不能污染缓存
    first[0]["filename"] = "被改了.md"
    assert (await store.alist_documents())[0]["filename"] == "a.md"


async def test_writes_invalidate_document_cache(tmp_path: Path) -> None:
    store, fake = make_store(tmp_path)

    await store.alist_documents()
    assert fake.get_calls == 1

    await store.aadd_chunks(
        ids=["a-0"],
        documents=["正文"],
        metadatas=[{"document_id": "a", "filename": "a.md", "title": "A"}],
        embeddings=[[0.0, 0.1]],
    )
    listed = await store.alist_documents()
    assert [item["document_id"] for item in listed] == ["a"]
    assert fake.get_calls == 2, "写入后缓存应失效"

    await store.adelete_document("a")
    assert await store.alist_documents() == []
    assert fake.get_calls == 3, "删除后缓存应失效"
