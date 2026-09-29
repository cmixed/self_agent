from __future__ import annotations

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

from app.core.agent_graph import build_graph
from app.models.state import initial_state
from app.services.task_service import TaskService, task_result

# planner -> outline -> 逐章写作 + 校验(2 章) -> summarizer
_HAPPY_STEPS = [
    "plan",
    "outline",
    "chapter_1",
    "validate_chapter_1",
    "chapter_2",
    "validate_document",
    "summarize",
]
_HAPPY_JSON_MODES = [True, True, False, True, False, True]


def _step_ids(state: dict) -> list[str]:
    return [result["step_id"] for result in state["step_results"]]


async def test_graph_end_to_end_completes() -> None:
    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON])
    graph = build_graph(provider, max_retries=0)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-e2e"))

    assert final["task_status"] == "completed"
    assert final["is_complete"] is True
    assert _step_ids(final) == _HAPPY_STEPS
    assert [section["title"] for section in final["outline"]] == ["引言", "chunk 大小的影响"]
    assert len(final["sections"]) == 2
    assert final["validation_result"]["passed"] is True
    assert final["retry_count"] == 0

    # 汇总结果包含文档标题与各章节
    assert final["final_answer"].startswith(f"# {PLAN_PAYLOAD['goal']}")
    assert "## 引言" in final["final_answer"]
    assert "## chunk 大小的影响" in final["final_answer"]
    assert DRAFT_TEXT in final["final_answer"]

    # planner / outline / 两次校验用 JSON 模式，两次写作不用
    assert provider.json_modes == _HAPPY_JSON_MODES


async def test_graph_rewrites_chapter_when_validation_fails() -> None:
    """章节校验失败 -> retry_writer -> 重写该章（章节数不变）。"""
    provider = ScriptedProvider(
        [
            PLAN_JSON,
            OUTLINE_JSON,
            "初稿第一章",
            validation_fail_json("retry_writer", ["第一章过于空泛"]),
            "修正后的第一章",
        ]
    )
    graph = build_graph(provider, max_retries=2)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-retry"))

    assert final["task_status"] == "completed"
    assert len(final["sections"]) == 2
    assert final["sections"][0]["content"] == "修正后的第一章"
    assert final["retry_count"] == 1
    assert final["validation_result"]["passed"] is True
    assert _step_ids(final) == [
        "plan",
        "outline",
        "chapter_1",
        "validate_chapter_1",
        "chapter_1",
        "validate_chapter_1",
        "chapter_2",
        "validate_document",
        "summarize",
    ]
    # 重写提示词里带上了校验问题
    assert "第一章过于空泛" in provider.calls[4][1].content


async def test_graph_replans_when_validation_says_replan() -> None:
    """整篇校验失败且判定为计划问题 -> replan 回到 planner 并重置章节。"""
    provider = ScriptedProvider(
        [
            PLAN_JSON,
            OUTLINE_JSON,
            "初稿第一章",
            validation_fail_json("replan", ["计划拆分不合理"]),
            PLAN_JSON,
            OUTLINE_JSON,
            "重新规划后的第一章",
        ]
    )
    graph = build_graph(provider, max_retries=2)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-replan"))

    assert final["task_status"] == "completed"
    assert _step_ids(final).count("plan") == 2
    assert len(final["sections"]) == 2
    assert final["sections"][0]["content"] == "重新规划后的第一章"
    assert final["retry_count"] == 1
    assert final["validation_result"]["passed"] is True


async def test_graph_stops_retrying_at_limit() -> None:
    """超过 MAX_RETRIES 后不再重试，安全结束并输出当前结果（§16）。"""
    provider = ScriptedProvider(
        [PLAN_JSON, OUTLINE_JSON, "唯一初稿", validation_fail_json("retry_writer")]
    )
    graph = build_graph(provider, max_retries=1)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-cap"))

    assert final["task_status"] == "completed"
    assert final["retry_count"] == 1
    assert final["validation_result"]["passed"] is False
    assert _step_ids(final) == [
        "plan",
        "outline",
        "chapter_1",
        "validate_chapter_1",
        "summarize",
    ]
    assert "唯一初稿" in final["final_answer"]


async def test_task_service_assigns_task_id_and_runs_graph() -> None:
    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON])
    service = TaskService(provider, max_retries=0)

    state = await service.run("写一篇 RAG 综述")

    assert state["task_id"]
    assert state["task_status"] == "completed"
    assert DRAFT_TEXT in state["final_answer"]


async def test_graph_without_tool_skips_researcher() -> None:
    """未提供 RAG Tool 时（无检索能力），即使计划需要检索也不执行检索。"""
    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON])
    graph = build_graph(provider, max_retries=0)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-no-tool"))

    assert _step_ids(final) == _HAPPY_STEPS


async def test_graph_with_retrieval_runs_researcher_and_feeds_writer(
    tmp_path: Path,
) -> None:
    _, tool = await seed_knowledge_base(
        tmp_path, text="# RAG\n\n检索增强生成使用向量数据库存储文档向量。"
    )
    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON])
    graph = build_graph(provider, rag_tool_provider=lambda: tool, max_retries=0)

    final = await graph.ainvoke(initial_state("写一篇 RAG 综述", task_id="t-rag"))

    assert final["task_status"] == "completed"
    assert _step_ids(final) == [
        "plan",
        "research",
        "outline",
        "chapter_1",
        "validate_chapter_1",
        "chapter_2",
        "validate_document",
        "summarize",
    ]
    assert final["retrieved_documents"]

    # 写作调用（calls[2]、calls[4]）的输入应包含检索到的资料
    first_chapter_message = provider.calls[2][1].content
    assert "检索到的资料" in first_chapter_message
    assert "[1]" in first_chapter_message
    assert "rag.md" in first_chapter_message


async def test_task_service_reports_sources_and_references(tmp_path: Path) -> None:
    _, tool = await seed_knowledge_base(tmp_path, text="# RAG\n\n检索增强生成使用向量数据库。")
    service = TaskService(
        ScriptedProvider([PLAN_JSON, OUTLINE_JSON]),
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
    assert result["validation"]["passed"] is True
    assert result["retry_count"] == 0
