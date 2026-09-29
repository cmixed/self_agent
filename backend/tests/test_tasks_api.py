from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from fakes import (
    DRAFT_TEXT,
    OUTLINE_JSON,
    PLAN_JSON,
    PLAN_PAYLOAD,
    ScriptedProvider,
    seed_knowledge_base,
    validation_fail_json,
)
from fastapi.testclient import TestClient

from app.api.deps import build_task_repository, get_task_service
from app.main import create_app
from app.rag.tools import RagTool
from app.services.task_service import TaskService


def make_client(
    provider: ScriptedProvider,
    rag_tool_provider: Callable[[], RagTool] | None = None,
    *,
    max_retries: int = 0,
) -> TestClient:
    """用假的 LLM 与（可选的）临时知识库构建客户端，不触碰真实模型。"""
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: TaskService(
        provider,
        rag_tool_provider=rag_tool_provider,
        repository=build_task_repository(),
        max_retries=max_retries,
    )
    return TestClient(app)


def _provider() -> ScriptedProvider:
    return ScriptedProvider([PLAN_JSON, OUTLINE_JSON])


def test_create_task_returns_plan_outline_and_answer() -> None:
    provider = _provider()
    with make_client(provider) as client:
        response = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["task_id"]
    assert body["plan"]["goal"] == PLAN_PAYLOAD["goal"]
    assert [step["id"] for step in body["plan"]["steps"]] == ["research", "write"]
    assert body["outline"] == ["引言", "chunk 大小的影响"]
    # 未提供 RAG Tool 时不执行检索；逐章写作并逐章校验后汇总
    assert [result["step_id"] for result in body["step_results"]] == [
        "plan",
        "outline",
        "chapter_1",
        "validate_chapter_1",
        "chapter_2",
        "validate_chapter_2",
        "validate_document",
        "summarize",
    ]
    assert DRAFT_TEXT in body["final_answer"]
    assert body["sources"] == []
    assert body["validation"]["passed"] is True
    assert body["validation"]["target"] == "document"
    assert body["retry_count"] == 0
    assert body["failed_chapters"] == []


def test_create_task_with_retrieval_returns_sources(tmp_path: Path) -> None:
    _, tool = asyncio.run(
        seed_knowledge_base(tmp_path, text="# RAG\n\n检索增强生成使用向量数据库。")
    )
    provider = _provider()

    with make_client(provider, rag_tool_provider=lambda: tool) as client:
        response = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})

    assert response.status_code == 200
    body = response.json()
    assert [result["step_id"] for result in body["step_results"]] == [
        "plan",
        "research",
        "outline",
        "chapter_1",
        "validate_chapter_1",
        "chapter_2",
        "validate_chapter_2",
        "validate_document",
        "summarize",
    ]
    assert body["sources"]
    assert body["sources"][0]["filename"] == "rag.md"
    assert body["sources"][0]["index"] == 1
    assert "[1] rag.md" in body["final_answer"]


def test_create_task_reports_validation_failure_and_retry(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [PLAN_JSON, OUTLINE_JSON, "初稿", validation_fail_json("retry_writer")]
    )
    with make_client(provider, max_retries=2) as client:
        response = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})

    assert response.status_code == 200
    body = response.json()
    # 章节重试不占用 replan 预算
    assert body["retry_count"] == 0
    assert body["validation"]["passed"] is True
    assert body["failed_chapters"] == []


def test_create_task_marks_failed_chapter_and_keeps_going(tmp_path: Path) -> None:
    """每章独立预算：第 1 章达上限被标记，第 2 章仍继续产出。"""
    provider = ScriptedProvider(
        [PLAN_JSON, OUTLINE_JSON, "失败的第一章", validation_fail_json("retry_writer")]
    )
    with make_client(provider, max_retries=1) as client:
        response = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})

    assert response.status_code == 200
    body = response.json()
    assert body["failed_chapters"] == ["chapter_1"]
    assert [result["step_id"] for result in body["step_results"]] == [
        "plan",
        "outline",
        "chapter_1",
        "validate_chapter_1",
        "chapter_2",
        "validate_chapter_2",
        "validate_document",
        "summarize",
    ]
    assert "未通过校验" in body["final_answer"]


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


def test_create_task_is_persisted_and_queryable() -> None:
    """POST 后可通过 GET /api/tasks/{id} 查询到持久化记录（§18）。"""
    provider = _provider()
    with make_client(provider) as client:
        created = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})
        assert created.status_code == 200
        task_id = created.json()["task_id"]

        fetched = client.get(f"/api/tasks/{task_id}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["task_id"] == task_id
    assert body["status"] == "completed"
    assert body["query"] == "写一篇 RAG 综述"
    assert body["user_id"] == "local-user"
    assert body["created_at"]
    assert body["finished_at"]
    assert body["final_answer"] == created.json()["final_answer"]


def test_get_unknown_task_returns_404() -> None:
    with make_client(_provider()) as client:
        response = client.get("/api/tasks/does-not-exist")
    assert response.status_code == 404


def test_create_task_honours_user_header() -> None:
    with make_client(_provider()) as client:
        created = client.post(
            "/api/tasks",
            json={"query": "写一篇 RAG 综述"},
            headers={"X-User-Id": "alice"},
        )
        task_id = created.json()["task_id"]
        fetched = client.get(f"/api/tasks/{task_id}")

    assert fetched.json()["user_id"] == "alice"


def test_failed_task_is_persisted_as_failed() -> None:
    provider = ScriptedProvider(["这不是 JSON"], default="这也不是 JSON")
    with make_client(provider) as client:
        created = client.post("/api/tasks", json={"query": "写点东西"})
        assert created.status_code == 502

    # 失败也要落库，便于排查
    import asyncio

    from app.api.deps import build_task_repository

    record = asyncio.run(build_task_repository().get_task(created.json()["task_id"]))
    assert record is not None
    assert record.status == "failed"
    assert record.error_type == "llm_response_format_error"
