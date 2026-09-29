from __future__ import annotations

from pathlib import Path

from fakes import (
    DRAFT_TEXT,
    OUTLINE_JSON,
    PLAN_JSON,
    PLAN_PAYLOAD,
    ScriptedProvider,
    seed_knowledge_base,
)

from app.core.agent_graph import build_graph
from app.models.state import initial_state
from app.services.task_service import TaskService, task_result

# planner -> outline -> 逐章写作(2 章) -> summarizer
_CHAPTER_STEPS = ["plan", "outline", "chapter_1", "chapter_2", "summarize"]


async def test_graph_end_to_end_completes() -> None:
    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON, DRAFT_TEXT])
    graph = build_graph(provider, max_retries=0)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-e2e"))

    assert final["task_status"] == "completed"
    assert final["is_complete"] is True
    assert [result["step_id"] for result in final["step_results"]] == _CHAPTER_STEPS
    assert [section["title"] for section in final["outline"]] == ["引言", "chunk 大小的影响"]
    assert len(final["sections"]) == 2

    # 汇总结果包含文档标题与各章节
    assert final["final_answer"].startswith(f"# {PLAN_PAYLOAD['goal']}")
    assert "## 引言" in final["final_answer"]
    assert "## chunk 大小的影响" in final["final_answer"]
    assert DRAFT_TEXT in final["final_answer"]

    # messages 为追加语义：user + planner/outline/2 章/summarizer
    assert len(final["messages"]) == 6
    # planner 与 outline 用 JSON 模式，两次写作不用
    assert provider.json_modes == [True, True, False, False]


async def test_task_service_assigns_task_id_and_runs_graph() -> None:
    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON, DRAFT_TEXT])
    service = TaskService(provider, max_retries=0)

    state = await service.run("写一篇 RAG 综述")

    assert state["task_id"]
    assert state["task_status"] == "completed"
    assert DRAFT_TEXT in state["final_answer"]


async def test_graph_without_tool_skips_researcher() -> None:
    """未提供 RAG Tool 时（无检索能力），即使计划需要检索也不执行检索。"""
    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON, DRAFT_TEXT])
    graph = build_graph(provider, max_retries=0)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-no-tool"))

    assert [result["step_id"] for result in final["step_results"]] == _CHAPTER_STEPS


async def test_graph_with_retrieval_runs_researcher_and_feeds_writer(
    tmp_path: Path,
) -> None:
    _, tool = await seed_knowledge_base(
        tmp_path, text="# RAG\n\n检索增强生成使用向量数据库存储文档向量。"
    )
    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON, DRAFT_TEXT])
    graph = build_graph(provider, rag_tool_provider=lambda: tool, max_retries=0)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-rag"))

    assert final["task_status"] == "completed"
    assert [result["step_id"] for result in final["step_results"]] == [
        "plan",
        "research",
        *_CHAPTER_STEPS[1:],
    ]
    assert final["retrieved_documents"]

    # 写作调用（calls[2]、calls[3]）的输入应包含检索到的资料
    first_chapter_message = provider.calls[2][1].content
    assert "检索到的资料" in first_chapter_message
    assert "[1]" in first_chapter_message
    assert "rag.md" in first_chapter_message


async def test_task_service_reports_sources_and_references(tmp_path: Path) -> None:
    _, tool = await seed_knowledge_base(tmp_path, text="# RAG\n\n检索增强生成使用向量数据库。")
    service = TaskService(
        ScriptedProvider([PLAN_JSON, OUTLINE_JSON, DRAFT_TEXT]),
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

    # 参考来源由系统统一追加，编号与 sources 一致
    assert "## 参考来源" in result["final_answer"]
    assert "[1] rag.md" in result["final_answer"]
