from __future__ import annotations

import json
from typing import Any

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

from app.api.deps import get_task_service
from app.main import create_app
from app.services.task_service import TaskService

# planner -> outline -> 每章 (writer -> validator) -> 整篇校验 -> summarizer
_HAPPY_EVENTS = [
    "task_started",
    "planner_started",
    "planner_completed",
    "outline_started",
    "outline_completed",
    "writer_started",
    "writer_completed",
    "validator_started",
    "validator_completed",
    "writer_started",
    "writer_completed",
    "validator_started",
    "validator_completed",
    "validator_started",
    "validator_completed",
    "summarizer_started",
    "summarizer_completed",
    "task_completed",
]


async def collect(service: TaskService, query: str) -> list[dict[str, Any]]:
    return [event async for event in service.stream(query)]


def _provider() -> ScriptedProvider:
    return ScriptedProvider([PLAN_JSON, OUTLINE_JSON])


async def test_stream_emits_events_in_execution_order() -> None:
    service = TaskService(_provider(), max_retries=0)

    events = await collect(service, "写一篇 RAG 综述")
    names = [event["event"] for event in events]

    assert names == _HAPPY_EVENTS
    assert all(event["task_id"] for event in events)

    planned = next(event for event in events if event["event"] == "planner_completed")
    assert planned["plan"]["goal"] == PLAN_PAYLOAD["goal"]

    outlined = next(event for event in events if event["event"] == "outline_completed")
    assert outlined["outline"] == ["引言", "chunk 大小的影响"]

    # 写作进度按章节推进
    writer_done = [event for event in events if event["event"] == "writer_completed"]
    assert [event["step"] for event in writer_done] == ["chapter_1", "chapter_2"]
    started = [event for event in events if event["event"] == "writer_started"]
    assert started[0]["message"] == "正在撰写第 1 章"

    # 校验事件带结果信息
    validations = [event for event in events if event["event"] == "validator_completed"]
    assert [event["target"] for event in validations] == [
        "chapter_1",
        "chapter_2",
        "document",
    ]
    assert all(event["passed"] is True for event in validations)

    completed = events[-1]
    assert completed["result"]["status"] == "completed"
    assert DRAFT_TEXT in completed["result"]["final_answer"]


async def test_stream_emits_retrying_event_on_failure() -> None:
    provider = ScriptedProvider(
        [PLAN_JSON, OUTLINE_JSON, "初稿", validation_fail_json("retry_writer")]
    )
    service = TaskService(provider, max_retries=2)

    events = await collect(service, "写一篇 RAG 综述")
    names = [event["event"] for event in events]

    assert "retrying" in names
    retrying = next(event for event in events if event["event"] == "retrying")
    assert retrying["step"] == "chapter_1"
    assert retrying["retry_count"] == 1
    assert retrying["exhausted"] is False
    assert "重写" in retrying["message"]

    # 重试后仍能完成
    assert names[-1] == "task_completed"
    result = events[-1]["result"]
    assert result["validation"]["passed"] is True
    assert result["failed_chapters"] == []


async def test_stream_marks_exhausted_chapter_and_continues() -> None:
    """每章独立预算：达上限后跳过该章，其余章节继续。"""
    provider = ScriptedProvider(
        [PLAN_JSON, OUTLINE_JSON, "失败的第一章", validation_fail_json("retry_writer")]
    )
    service = TaskService(provider, max_retries=1)

    events = await collect(service, "写一篇 RAG 综述")
    retrying = next(event for event in events if event["event"] == "retrying")

    assert retrying["exhausted"] is True
    assert "上限" in retrying["message"]
    assert "跳过" in retrying["message"]

    result = events[-1]["result"]
    assert result["failed_chapters"] == ["chapter_1"]
    # 第 2 章仍然继续并被写入
    written = [event["step"] for event in events if event["event"] == "writer_completed"]
    assert written == ["chapter_1", "chapter_2"]
    assert "未通过校验" in result["final_answer"]


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
    # 覆盖 TaskService，避免测试接触真实 Embedding 模型
    app.dependency_overrides[get_task_service] = lambda: TaskService(_provider(), max_retries=0)

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
    assert DRAFT_TEXT in events[-1]["result"]["final_answer"]


async def test_stream_includes_researcher_events(tmp_path) -> None:
    _, tool = await seed_knowledge_base(tmp_path, text="# RAG\n\n检索增强生成使用向量数据库。")
    service = TaskService(_provider(), rag_tool_provider=lambda: tool, max_retries=0)

    events = await collect(service, "写一篇 RAG 综述")
    names = [event["event"] for event in events]

    assert names[:4] == [
        "task_started",
        "planner_started",
        "planner_completed",
        "researcher_started",
    ]
    assert names[4:6] == ["researcher_completed", "outline_started"]
    assert names[-1] == "task_completed"

    researcher_done = next(event for event in events if event["event"] == "researcher_completed")
    assert researcher_done["retrieved_count"] >= 1
    assert events[-1]["result"]["sources"]

    # 增量字段：researcher_completed 附带去重后的来源明细，且与最终 result.sources 一致
    assert researcher_done["sources"] == events[-1]["result"]["sources"]
    assert all(
        {"index", "filename", "page", "chunk_id", "score"} <= set(source)
        for source in researcher_done["sources"]
    )
    chunk_ids = [source["chunk_id"] for source in researcher_done["sources"]]
    assert len(chunk_ids) == len(set(chunk_ids))


async def test_stream_reports_outline_truncation() -> None:
    """大纲被上限截断时，outline_completed 消息要说明清楚（不静默丢章节）。"""
    import json as jsonlib

    plan = {
        "goal": "写综述",
        "needs_retrieval": False,
        "steps": [{"id": "w", "type": "writing", "description": "撰写"}],
    }
    outline = {"sections": [{"title": f"第 {i} 章"} for i in range(1, 11)]}
    provider = ScriptedProvider(
        [jsonlib.dumps(plan, ensure_ascii=False), jsonlib.dumps(outline, ensure_ascii=False)],
        default_text="正文",
    )
    service = TaskService(provider, max_retries=0, target_sections=4, max_sections=5)

    events = [event async for event in service.stream("写综述")]

    outline_event = next(event for event in events if event["event"] == "outline_completed")
    assert len(outline_event["outline"]) == 5
    assert outline_event["truncated"] is True
    assert "已按上限 5 截断" in outline_event["message"]
