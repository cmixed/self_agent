"""检索范围：Chroma 过滤、链路透传、任务级端到端（sources 只能来自范围内）。"""

from __future__ import annotations

import json

from fakes import (
    OUTLINE_JSON,
    PLAN_JSON,
    FakeEmbeddingProvider,
    ScriptedProvider,
)

from app.api.deps import get_document_service, get_task_service
from app.main import create_app
from app.models.state import RetrievalScope
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.rag.tools import RagTool
from app.services.document_service import DocumentService
from app.services.task_service import TaskService


def _store(tmp_path) -> ChromaStore:
    return ChromaStore(
        persist_dir=tmp_path / "chroma",
        collection_name="scope_kb",
        embedding_signature=FakeEmbeddingProvider().signature(),
    )


async def _ingest(service: DocumentService, filename: str, text: str) -> str:
    info = await service.ingest(filename=filename, content=text.encode())
    return info.document_id


def _service(store: ChromaStore, tmp_path) -> DocumentService:
    return DocumentService(
        provider_factory=lambda: FakeEmbeddingProvider(),
        store=store,
        documents_dir=tmp_path / "documents",
        chunk_size=200,
        chunk_overlap=20,
    )


# --- Chroma 过滤语义 ---


async def test_query_filters_by_document_ids(tmp_path) -> None:
    store = _store(tmp_path)
    provider = FakeEmbeddingProvider()
    service = _service(store, tmp_path)
    doc_a = await _ingest(service, "a.md", "RAG 使用向量检索增强生成能力，分块影响召回。")
    doc_b = await _ingest(service, "b.md", "RAG 使用向量检索增强生成能力，分块影响召回。")

    embedding = await provider.embed_query("RAG 向量检索")

    all_hits = await store.aquery(embedding=embedding, top_k=10)
    only_a = await store.aquery(embedding=embedding, top_k=10, document_ids=[doc_a])
    only_b = await store.aquery(embedding=embedding, top_k=10, document_ids=[doc_b])

    assert {hit.metadata["document_id"] for hit in all_hits} == {doc_a, doc_b}
    assert {hit.metadata["document_id"] for hit in only_a} == {doc_a}
    assert {hit.metadata["document_id"] for hit in only_b} == {doc_b}


async def test_empty_document_ids_returns_nothing(tmp_path) -> None:
    """空列表表示"范围内没有文档"，绝不能退化成检索全部。"""
    store = _store(tmp_path)
    service = _service(store, tmp_path)
    await _ingest(service, "a.md", "RAG 使用向量检索增强生成能力。")
    embedding = await FakeEmbeddingProvider().embed_query("RAG")

    assert await store.aquery(embedding=embedding, top_k=5, document_ids=[]) == []
    assert await store.aquery(embedding=embedding, top_k=5, document_ids=None) != []


async def test_retriever_and_tool_pass_scope_through(tmp_path) -> None:
    store = _store(tmp_path)
    provider = FakeEmbeddingProvider()
    service = _service(store, tmp_path)
    doc_a = await _ingest(service, "a.md", "RAG 使用向量检索增强生成能力，分块影响召回质量。")
    await _ingest(service, "b.md", "RAG 使用向量检索增强生成能力，分块影响召回质量。")

    retriever = Retriever(provider, store, top_k=10)
    documents = await retriever.retrieve("RAG 检索", document_ids=[doc_a])
    assert {item["document_id"] for item in documents} == {doc_a}

    tool = RagTool(retriever)
    assert {item["document_id"] for item in await tool.search("RAG", document_ids=[doc_a])} == {
        doc_a
    }


# --- 任务端到端：sources 只能在范围内 ---


async def test_task_sources_are_restricted_to_scope(tmp_path) -> None:
    store = _store(tmp_path)
    document_service = _service(store, tmp_path)
    doc_a = await _ingest(document_service, "a.md", "RAG 使用向量检索增强生成能力，分块影响召回。")
    await _ingest(document_service, "b.md", "RAG 使用向量检索增强生成能力，分块影响召回。")

    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON], default_text="正文内容")
    service = TaskService(
        provider,
        rag_tool_provider=lambda: RagTool(Retriever(FakeEmbeddingProvider(), store, top_k=5)),
        max_retries=0,
    )
    scope: RetrievalScope = {"document_ids": [doc_a], "label": "仅 a.md"}

    events = [event async for event in service.stream("写综述", retrieval_scope=scope)]

    result = events[-1]["result"]
    assert events[-1]["event"] == "task_completed"
    assert result["sources"], "范围内应检索到来源"
    assert {item["document_id"] for item in result["sources"]} == {doc_a}
    assert result["scope"] == {
        "label": "仅 a.md",
        "document_count": 1,
        "category_ids": [],
        "selected_document_ids": [],
    }


async def test_task_without_scope_uses_whole_kb(tmp_path) -> None:
    store = _store(tmp_path)
    document_service = _service(store, tmp_path)
    doc_a = await _ingest(document_service, "a.md", "RAG 使用向量检索增强生成能力。")
    doc_b = await _ingest(document_service, "b.md", "RAG 使用向量检索增强生成能力。")

    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON], default_text="正文内容")
    service = TaskService(
        provider,
        rag_tool_provider=lambda: RagTool(Retriever(FakeEmbeddingProvider(), store, top_k=5)),
        max_retries=0,
    )

    events = [event async for event in service.stream("写综述")]

    result = events[-1]["result"]
    assert {item["document_id"] for item in result["sources"]} == {doc_a, doc_b}
    assert result["scope"] is None


async def test_resume_keeps_frozen_scope(tmp_path) -> None:
    """续跑沿用 checkpoint 里冻结的范围；期间往类别加文档不影响本次。"""
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.llm.base import LLMError

    store = _store(tmp_path)
    document_service = _service(store, tmp_path)
    doc_a = await _ingest(document_service, "a.md", "RAG 使用向量检索增强生成能力，分块影响召回。")
    doc_b = await _ingest(document_service, "b.md", "RAG 使用向量检索增强生成能力，分块影响召回。")

    connection = await aiosqlite.connect(tmp_path / "cp.db")
    saver = AsyncSqliteSaver(connection)
    await saver.setup()

    class Failing(ScriptedProvider):
        async def chat(self, messages, *, temperature=0.7, max_tokens=None, json_mode=False):
            if len(self.calls) >= 3:
                raise LLMError("模拟中断")
            return await super().chat(
                messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
            )

    task_id = "scope-resume"
    failing = Failing([PLAN_JSON, OUTLINE_JSON])
    service = TaskService(
        failing,
        rag_tool_provider=lambda: RagTool(Retriever(FakeEmbeddingProvider(), store, top_k=5)),
        checkpointer=saver,
        max_retries=0,
    )
    _ = [
        event
        async for event in service.stream(
            "写综述", task_id=task_id, retrieval_scope={"document_ids": [doc_a], "label": "A"}
        )
    ]

    snapshot = await service.snapshot(task_id)
    assert snapshot is not None
    assert snapshot["retrieval_scope"]["document_ids"] == [doc_a]
    assert snapshot["retrieval_scope"]["label"] == "A"

    # 续跑：范围内仍只有 a.md（checkpoint 冻结），b.md 不会被检索到
    resuming = ScriptedProvider([])
    service2 = TaskService(
        resuming,
        rag_tool_provider=lambda: RagTool(Retriever(FakeEmbeddingProvider(), store, top_k=5)),
        checkpointer=saver,
        max_retries=0,
    )
    events = [event async for event in service2.resume(task_id)]
    result = events[-1]["result"]
    assert {item["document_id"] for item in result["sources"]} == {doc_a}
    assert doc_b not in {item["document_id"] for item in result["sources"]}


# --- API：范围解析与空范围拦截 ---


def _api_app(tmp_path):
    store = _store(tmp_path)
    document_service = _service(store, tmp_path)

    app = create_app()
    app.dependency_overrides[get_document_service] = lambda: document_service
    app.dependency_overrides[get_task_service] = lambda: TaskService(
        ScriptedProvider([PLAN_JSON, OUTLINE_JSON], default_text="正文内容"),
        rag_tool_provider=lambda: RagTool(Retriever(FakeEmbeddingProvider(), store, top_k=5)),
        max_retries=0,
    )
    return app, document_service


def test_task_scope_resolution_and_empty_scope_rejection(tmp_path) -> None:
    from fastapi.testclient import TestClient

    app, document_service = _api_app(tmp_path)
    with TestClient(app) as client:
        import asyncio

        doc_a = asyncio.run(
            document_service.ingest(
                filename="a.md", content="RAG 使用向量检索增强生成能力。".encode()
            )
        ).document_id
        doc_b = asyncio.run(
            document_service.ingest(
                filename="b.md", content="RAG 使用向量检索增强生成能力。".encode()
            )
        ).document_id

        category = client.post("/api/categories", json={"name": "只有A"}).json()
        client.put(
            f"/api/documents/{doc_a}/categories",
            json={"category_ids": [category["category_id"]]},
        )

        # 选类别 → 解析出 a.md
        response = client.post(
            "/api/tasks/stream",
            json={"query": "写综述", "scope": {"category_ids": [category["category_id"]]}},
        )
        assert response.status_code == 200
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        result = events[-1]["result"]
        assert {item["document_id"] for item in result["sources"]} == {doc_a}
        assert result["scope"]["document_count"] == 1
        assert result["scope"]["category_ids"] == [category["category_id"]]

        # 空类别 → 409，不静默退化成全部
        empty = client.post("/api/categories", json={"name": "空类"}).json()
        blocked = client.post(
            "/api/tasks/stream",
            json={"query": "写综述", "scope": {"category_ids": [empty["category_id"]]}},
        )
        assert blocked.status_code == 409
        assert "没有任何文档" in blocked.json()["detail"]

        # 单个文件范围
        single = client.post(
            "/api/tasks/stream",
            json={"query": "写综述", "scope": {"document_ids": [doc_b]}},
        )
        single_result = [
            json.loads(line[6:]) for line in single.text.splitlines() if line.startswith("data: ")
        ][-1]["result"]
        assert {item["document_id"] for item in single_result["sources"]} == {doc_b}
        assert single_result["scope"]["selected_document_ids"] == [doc_b]


def test_retrieval_mode_none_skips_kb_and_selected_requires_scope(tmp_path) -> None:
    """显式「不检索」不碰知识库；「指定范围」为空必须 409，不能退化成全部。"""
    from fastapi.testclient import TestClient

    app, _ = _api_app(tmp_path)
    with TestClient(app) as client:
        # 指定范围但什么都没选 → 409
        blocked = client.post(
            "/api/tasks/stream",
            json={"query": "写综述", "retrieval_mode": "selected"},
        )
        assert blocked.status_code == 409
        assert "至少需要选择" in blocked.json()["detail"]

        # 不检索：即使传了 scope 也忽略，planner 必须被强制为 needs_retrieval=false
        response = client.post(
            "/api/tasks/stream",
            json={
                "query": "写综述",
                "retrieval_mode": "none",
                "scope": {"document_ids": ["should-be-ignored"]},
            },
        )
        assert response.status_code == 200
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        planned = next(event for event in events if event["event"] == "planner_completed")
        assert planned["plan"]["needs_retrieval"] is False
        result = events[-1]["result"]
        assert result["retrieval_mode"] == "none"
        assert result["sources"] == []
        assert result["scope"] is None
        assert not any(event["event"].startswith("researcher_") for event in events)


def test_task_profile_retrieval_modes() -> None:
    from app.models.task_profile import resolve_profile

    selected = resolve_profile("总结一下", retrieval_mode="selected")
    assert selected.needs_retrieval is True

    disabled = resolve_profile("根据我的资料写综述", retrieval_mode="none")
    assert disabled.needs_retrieval is False

    default = resolve_profile("你好")
    assert default.needs_retrieval is False
