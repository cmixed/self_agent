from __future__ import annotations

import asyncio
import json
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

from app.api.deps import (
    build_memory_repository,
    build_task_repository,
    get_memory_service,
    get_task_service,
)
from app.main import create_app
from app.rag.tools import RagTool
from app.services.memory_service import MemoryService
from app.services.task_service import TaskService


def make_client(
    provider: ScriptedProvider,
    rag_tool_provider: Callable[[], RagTool] | None = None,
    *,
    max_retries: int = 0,
    memory_provider: ScriptedProvider | None = None,
) -> TestClient:
    """用假的 LLM 与（可选的）临时知识库构建客户端。

    长期记忆服务默认不接 LLM（提取为 no-op），确保测试完全离线；
    需要验证自动提取时传入 ``memory_provider``。
    """
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: TaskService(
        provider,
        rag_tool_provider=rag_tool_provider,
        repository=build_task_repository(),
        max_retries=max_retries,
    )
    app.dependency_overrides[get_memory_service] = lambda: MemoryService(
        build_memory_repository(), memory_provider
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


def test_stored_preferences_are_injected_into_task() -> None:
    """SQLite 中的长期偏好会并入任务的 user_preferences（请求可覆盖）。"""
    provider = _provider()
    with make_client(provider) as client:
        asyncio.run(build_memory_repository().set_preference("local-user", "style", "学术严谨"))
        created = client.post(
            "/api/tasks",
            json={"query": "写一篇 RAG 综述", "user_preferences": {"format": "Markdown"}},
        )

    assert created.status_code == 200
    planner_prompt = provider.calls[0][1].content
    assert "style=学术严谨" in planner_prompt
    assert "format=Markdown" in planner_prompt


_EXTRACTION_JSON = json.dumps(
    {
        "preferences": [{"key": "language", "value": "使用中文"}],
        "memories": [{"kind": "task_type", "content": "经常撰写技术综述"}],
    },
    ensure_ascii=False,
)


def test_task_completion_extracts_long_term_memory() -> None:
    """任务完成后用一次结构化调用提取长期记忆。"""
    provider = _provider()
    with make_client(provider, memory_provider=ScriptedProvider([_EXTRACTION_JSON])) as client:
        response = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})
        assert response.status_code == 200
        profile = client.get("/api/memory").json()

    assert profile["preferences"] == {"language": "使用中文"}
    assert [memory["content"] for memory in profile["memories"]] == ["经常撰写技术综述"]


def test_memory_extraction_failure_does_not_break_task() -> None:
    """提取失败只记日志，任务结果照常返回。"""
    provider = _provider()
    # 提取调用返回非 JSON -> 解析失败 -> 被吞掉（best-effort）
    with make_client(
        provider, memory_provider=ScriptedProvider(["不是 JSON"], default="也不是 JSON")
    ) as client:
        response = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})
        profile = client.get("/api/memory").json()

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert profile["preferences"] == {}
    assert profile["memories"] == []


def test_list_tasks_returns_newest_first_and_is_user_scoped() -> None:
    # 每次请求使用独立的假 Provider（响应是消耗式的）
    with make_client(_provider()) as client:
        first = client.post("/api/tasks", json={"query": "任务一"}).json()
    with make_client(_provider()) as client:
        second = client.post("/api/tasks", json={"query": "任务二"}).json()
    with make_client(_provider()) as client:
        client.post("/api/tasks", json={"query": "别人的任务"}, headers={"X-User-Id": "bob"})
    with make_client(_provider()) as client:
        listed = client.get("/api/tasks")

    assert listed.status_code == 200
    tasks = listed.json()["tasks"]
    assert [t["task_id"] for t in tasks] == [second["task_id"], first["task_id"]]
    assert tasks[0]["query"] == "任务二"
    assert tasks[0]["status"] == "completed"
    assert tasks[0]["created_at"]
    assert tasks[0]["finished_at"]
    assert "final_answer" not in tasks[0]  # 列表项不返回正文

    with make_client(_provider()) as client:
        bob = client.get("/api/tasks", headers={"X-User-Id": "bob"}).json()["tasks"]
    assert [t["query"] for t in bob] == ["别人的任务"]


def test_list_tasks_limit_is_validated() -> None:
    with make_client(_provider()) as client:
        assert client.get("/api/tasks?limit=0").status_code == 422
        assert client.get("/api/tasks?limit=101").status_code == 422
