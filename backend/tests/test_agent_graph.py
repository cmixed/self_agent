from __future__ import annotations

from pathlib import Path

from fakes import (
    DRAFT_TEXT,
    PLAN_JSON,
    PLAN_PAYLOAD,
    ScriptedProvider,
    seed_knowledge_base,
)

from app.core.agent_graph import build_graph
from app.models.state import initial_state
from app.services.task_service import TaskService, task_result


async def test_graph_end_to_end_completes() -> None:
    provider = ScriptedProvider([PLAN_JSON, DRAFT_TEXT])
    graph = build_graph(provider, max_retries=0)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-e2e"))

    assert final["task_status"] == "completed"
    assert final["is_complete"] is True
    assert final["final_answer"] == DRAFT_TEXT.strip()
    assert final["plan"]["goal"] == PLAN_PAYLOAD["goal"]
    # 节点按顺序执行：planner -> writer -> summarizer
    assert [result["step_id"] for result in final["step_results"]] == [
        "plan",
        "write",
        "summarize",
    ]
    # messages 为追加语义：user + 3 个节点各一条
    assert [message.role for message in final["messages"]] == [
        "user",
        "assistant",
        "assistant",
        "assistant",
    ]
    # planner 用 JSON 模式，writer 不用
    assert provider.json_modes == [True, False]


async def test_task_service_assigns_task_id_and_runs_graph() -> None:
    provider = ScriptedProvider([PLAN_JSON, DRAFT_TEXT])
    service = TaskService(provider, max_retries=0)

    state = await service.run("写一篇 RAG 综述")

    assert state["task_id"]
    assert state["task_status"] == "completed"
    assert state["final_answer"] == DRAFT_TEXT.strip()


async def test_graph_without_tool_skips_researcher() -> None:
    """未提供 RAG Tool 时（无检索能力），即使计划需要检索也直接写作。"""
    provider = ScriptedProvider([PLAN_JSON, DRAFT_TEXT])
    graph = build_graph(provider, max_retries=0)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-no-tool"))

    assert [result["step_id"] for result in final["step_results"]] == [
        "plan",
        "write",
        "summarize",
    ]


async def test_graph_with_retrieval_runs_researcher_and_feeds_writer(tmp_path: Path) -> None:
    _, tool = await seed_knowledge_base(
        tmp_path, text="# RAG\n\n检索增强生成使用向量数据库存储文档向量。"
    )
    provider = ScriptedProvider([PLAN_JSON, DRAFT_TEXT])
    graph = build_graph(provider, rag_tool_provider=lambda: tool, max_retries=0)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-rag"))

    assert final["task_status"] == "completed"
    assert [result["step_id"] for result in final["step_results"]] == [
        "plan",
        "research",
        "write",
        "summarize",
    ]
    assert final["retrieved_documents"]

    # writer 是第二次 LLM 调用，其输入应包含检索到的资料
    writer_user_message = provider.calls[1][1].content
    assert "检索到的资料" in writer_user_message
    assert "[1]" in writer_user_message
    assert "rag.md" in writer_user_message


async def test_task_service_reports_sources(tmp_path: Path) -> None:
    _, tool = await seed_knowledge_base(tmp_path, text="# RAG\n\n检索增强生成使用向量数据库。")
    service = TaskService(
        ScriptedProvider([PLAN_JSON, DRAFT_TEXT]),
        rag_tool_provider=lambda: tool,
        max_retries=0,
    )

    state = await service.run("写一篇 RAG 综述")
    result = task_result(state)

    assert result["sources"]
    first = result["sources"][0]
    assert first["index"] == 1
    assert first["filename"] == "rag.md"
    assert first["score"] is not None
