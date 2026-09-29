from __future__ import annotations

from fakes import DRAFT_TEXT, PLAN_JSON, PLAN_PAYLOAD, ScriptedProvider
from fastapi.testclient import TestClient

from app.api.deps import get_llm_provider
from app.main import create_app


def make_client(provider: ScriptedProvider) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_llm_provider] = lambda: provider
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
    assert [result["step_id"] for result in body["step_results"]] == [
        "plan",
        "write",
        "summarize",
    ]


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
