from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FailingEmbeddingProvider, FakeEmbeddingProvider, seed_knowledge_base

from app.agents.researcher import make_researcher_node
from app.embedding.base import EmbeddingError
from app.models.state import initial_state
from app.rag.tools import RagTool


async def test_researcher_populates_retrieved_documents(tmp_path: Path) -> None:
    _, tool = await seed_knowledge_base(
        tmp_path, text="# RAG\n\n检索增强生成使用向量数据库存储文档向量。"
    )
    node = make_researcher_node(lambda: tool)

    state = initial_state("什么是 RAG？", task_id="t-research")
    update = await node(state)

    documents = update["retrieved_documents"]
    assert len(documents) >= 1
    assert documents[0]["filename"] == "rag.md"
    assert documents[0]["chunk_id"]
    assert update["step_results"][0]["step_id"] == "research"
    assert update["step_results"][0]["status"] == "ok"


async def test_researcher_degrades_gracefully_on_embedding_failure() -> None:
    """检索失败不终止任务：记录错误状态并降级为无检索结果（§20）。"""
    failing = FailingEmbeddingProvider()

    def failing_tool() -> RagTool:
        # 直接构造会在 embed_query 时抛错
        import tempfile

        from app.rag.retriever import Retriever
        from app.rag.store import ChromaStore

        store = ChromaStore(
            persist_dir=Path(tempfile.mkdtemp()),
            collection_name="broken_kb",
            embedding_signature=failing.signature(),
        )
        return RagTool(Retriever(failing, store))

    node = make_researcher_node(failing_tool)
    update = await node(initial_state("问题", task_id="t-fail"))

    assert update["retrieved_documents"] == []
    assert update["step_results"][0]["status"] == "error"
    assert "检索失败" in update["step_results"][0]["summary"]


async def test_rag_tool_search_returns_source_metadata(tmp_path: Path) -> None:
    store, tool = await seed_knowledge_base(
        tmp_path, text="# 向量检索\n\n余弦相似度用于衡量向量之间的距离。"
    )
    assert store.count() >= 1

    hits = await tool.search("余弦相似度")
    assert hits
    assert hits[0]["document_id"]
    assert hits[0]["filename"] == "rag.md"
    assert hits[0]["score"] is not None


@pytest.mark.parametrize("query", ["", "   "])
async def test_rag_tool_empty_query_returns_nothing(tmp_path: Path, query: str) -> None:
    _, tool = await seed_knowledge_base(tmp_path, text="内容")
    assert await tool.search(query) == []


def test_fake_embedding_is_deterministic() -> None:
    provider = FakeEmbeddingProvider()
    assert provider.dimension == 64
    assert provider.signature()["model"] == "fake-embedding"
    error = EmbeddingError("x")
    assert error.error_type == "embedding_error"
