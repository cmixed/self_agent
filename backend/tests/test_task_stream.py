from __future__ import annotations

import json
from typing import Any

from fakes import DRAFT_TEXT, PLAN_JSON, PLAN_PAYLOAD, ScriptedProvider
from fastapi.testclient import TestClient

from app.api.deps import get_llm_provider
from app.main import create_app
from app.services.task_service import TaskService


async def collect(service: TaskService, query: str) -> list[dict[str, Any]]:
    return [event async for event in service.stream(query)]


async def test_stream_emits_events_in_execution_order() -> None:
    provider = ScriptedProvider([PLAN_JSON, DRAFT_TEXT])
    service = TaskService(provider, max_retries=0)

    events = await collect(service, "写一篇 RAG 综述")
    names = [event["event"] for event in events]

    assert names == [
        "task_started",
        "planner_started",
        "planner_completed",
        "writer_started",
        "writer_completed",
        "summarizer_started",
        "summarizer_completed",
        "task_completed",
    ]
    assert all(event["task_id"] for event in events)

    planned = next(event for event in events if event["event"] == "planner_completed")
    assert planned["plan"]["goal"] == PLAN_PAYLOAD["goal"]

    completed = events[-1]
    assert completed["result"]["status"] == "completed"
    assert completed["result"]["final_answer"] == DRAFT_TEXT.strip()


async def test_stream_converts_error_to_task_failed() -> None:
    provider = ScriptedProvider(["这不是 JSON"], default="这也不是 JSON")
    service = TaskService(provider, max_retries=1)

    events = await collect(service, "写点东西")

    assert events[-1]["event"] == "task_failed"
    assert events[-1]["status"] == "error"
    assert events[-1]["error_type"] == "llm_response_format_error"
    assert "task_completed" not in [event["event"] for event in events]


def test_stream_endpoint_emits_sse_frames() -> None:
    app = create_app()
    app.dependency_overrides[get_llm_provider] = lambda: ScriptedProvider([PLAN_JSON, DRAFT_TEXT])

    with (
        TestClient(app) as client,
        client.stream("POST", "/api/tasks/stream", json={"query": "写一篇 RAG 综述"}) as response,
    ):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    frames = [line[len("data: ") :] for line in body.splitlines() if line.startswith("data: ")]
    events = [json.loads(frame) for frame in frames]
    assert events[0]["event"] == "task_started"
    assert events[-1]["event"] == "task_completed"
    assert events[-1]["result"]["final_answer"] == DRAFT_TEXT.strip()
