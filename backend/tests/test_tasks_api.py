from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from fakes import DRAFT_TEXT, PLAN_JSON, PLAN_PAYLOAD, ScriptedProvider, seed_knowledge_base
from fastapi.testclient import TestClient

from app.api.deps import get_task_service
from app.main import create_app
from app.rag.tools import RagTool
from app.services.task_service import TaskService


def make_client(
    provider: ScriptedProvider,
    rag_tool_provider: Callable[[], RagTool] | None = None,
) -> TestClient:
    """用假的 LLM 与（可选的）临时知识库构建客户端，不触碰真实模型。"""
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: TaskService(
        provider, rag_tool_provider=rag_tool_provider, max_retries=0
    )
    return TestClient(app)


def test_create_task_returns_plan_and_answer() -> None:
    provider = ScriptedProvider([PLAN_JSON, DRAFT_TEXT])
    with make_client(provider) as client:
        response = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["task_id"]
    assert body["plan"]["goal"] == PLAN_PAYLOAD["goal"]
    assert [step["id"] for step in body["plan"]["steps"]] == ["research", "write"]
    assert body["final_answer"] == DRAFT_TEXT.strip()
    # 未提供 RAG Tool 时不执行检索，直接写作
    assert [result["step_id"] for result in body["step_results"]] == [
        "plan",
        "write",
        "summarize",
    ]
    assert body["sources"] == []


def test_create_task_with_retrieval_returns_sources(tmp_path: Path) -> None:
    _, tool = asyncio.run(
        seed_knowledge_base(tmp_path, text="# RAG\n\n检索增强生成使用向量数据库。")
    )
    provider = ScriptedProvider([PLAN_JSON, DRAFT_TEXT])

    with make_client(provider, rag_tool_provider=lambda: tool) as client:
        response = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})

    assert response.status_code == 200
    body = response.json()
    assert [result["step_id"] for result in body["step_results"]] == [
        "plan",
        "research",
        "write",
        "summarize",
    ]
    assert body["sources"]
    assert body["sources"][0]["filename"] == "rag.md"
    assert body["sources"][0]["index"] == 1


def test_create_task_rejects_empty_query() -> None:
    with make_client(ScriptedProvider()) as client:
        response = client.post("/api/tasks", json={"query": ""})
    assert response.status_code == 422


def test_create_task_maps_planner_format_error_to_502() -> None:
    # 始终返回非 JSON，planner 有限重试后抛出格式错误
    provider = ScriptedProvider(["这不是 JSON"], default="这也不是 JSON")
    with make_client(provider) as client:
        response = client.post("/api/tasks", json={"query": "写点东西"})

    assert response.status_code == 502
    assert response.json()["error_type"] == "llm_response_format_error"
