"""LangGraph 工作流编排。

只负责节点连接与条件路由，业务逻辑在 ``app/agents/`` 中（见 AGENTS.md §4.2）。

当前拓扑（Phase 4B + 技能）：

    START → planner ──(需要检索)──→ researcher ──┐
                  │                             ↓
                  ├──(不需要检索)──────────→ skills ⇄ skills（逐个执行技能步骤）
                  │                             ↓
                  │                          outline → writer → validator ──┐
                  │                                            ↑           │
                  │                    (还有章节 / retry_writer) └───────────┤
                  │                                                        │
                  │                        (replan 且未超限) → planner ──────┘
                  │                                                        │
                  │              (通过且写完 / 重试达上限) ↓               │
                  └──(无计划)──→ END                    summarizer → END

无技能目录时不挂载 skills 节点，拓扑退化为原有形态（researcher → outline）。

重试次数由 ``MAX_RETRIES`` 限制，超限后进入 summarizer 安全结束（§16）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.outline import make_outline_node
from app.agents.planner import make_planner_node, make_route_after_planner
from app.agents.researcher import make_researcher_node
from app.agents.skills import (
    MAX_SKILL_STEPS,
    CatalogEntry,
    make_route_after_skills,
    make_skills_node,
)
from app.agents.summarizer import make_summarizer_node
from app.agents.validator import make_route_after_validation, make_validator_node
from app.agents.writer import make_writer_node
from app.core.limits import (
    DEFAULT_MAX_SECTIONS,
    DEFAULT_TARGET_SECTIONS,
    DEFAULT_TOTAL_CHARS,
)
from app.llm.base import LLMProvider
from app.models.state import AgentState
from app.rag.tools import RagTool


def recursion_limit(max_retries: int, *, max_sections: int = DEFAULT_MAX_SECTIONS) -> int:
    """LangGraph 的最大超步数（安全兜底）。

    图本身的循环都由「章节数上限 max_sections」与「重试预算」约束，这里给出一个
    覆盖最坏情况的宽松上界，避免触发 LangGraph 默认值 25 而中断任务。
    """
    retries = max(0, max_retries)
    sections = max(1, max_sections)
    per_pass = (
        5
        + (MAX_SKILL_STEPS + 1)  # 技能步骤逐个执行 + 最后一次路由
        + 2 * sections * (1 + retries)
        + 2  # 整篇校验 + 汇总
    )  # planner/researcher/outline + 技能 + 各章 + 整篇校验
    return (retries + 1) * per_pass + 10


def build_graph(
    llm: LLMProvider,
    *,
    rag_tool_provider: Callable[[], RagTool] | None = None,
    skill_catalog: Sequence[CatalogEntry] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    max_retries: int = 2,
    target_sections: int = DEFAULT_TARGET_SECTIONS,
    max_sections: int = DEFAULT_MAX_SECTIONS,
    target_total_chars: int = DEFAULT_TOTAL_CHARS,
) -> CompiledStateGraph:
    """构建并编译 Agent 图。

    未提供 ``rag_tool_provider`` 时不挂载 researcher 节点；``skill_catalog``
    为空时不挂载 skills 节点，各自退化为不含该阶段的流程（便于测试与无知识库场景）。
    """
    catalog = list(skill_catalog or [])
    graph = StateGraph(AgentState)

    graph.add_node(
        "planner", make_planner_node(llm, max_retries=max_retries, skill_catalog=catalog)
    )
    graph.add_node(
        "outline",
        make_outline_node(
            llm,
            max_retries=max_retries,
            target_sections=target_sections,
            max_sections=max_sections,
        ),
    )
    graph.add_node(
        "writer",
        make_writer_node(
            llm,
            max_retries=max_retries,
            max_sections=max_sections,
            target_total_chars=target_total_chars,
        ),
    )
    graph.add_node(
        "validator",
        make_validator_node(
            llm,
            max_retries=max_retries,
            max_sections=max_sections,
            target_total_chars=target_total_chars,
        ),
    )
    graph.add_node(
        "summarizer", make_summarizer_node(max_retries=max_retries, max_sections=max_sections)
    )

    if catalog:
        graph.add_node("skills", make_skills_node(llm, catalog))
        graph.add_conditional_edges(
            "skills",
            make_route_after_skills(),
            {"skills": "skills", "outline": "outline"},
        )
    next_stage = "skills" if catalog else "outline"

    routes: dict[str, str] = {"outline": "outline", "end": END}
    if catalog:
        routes["skills"] = "skills"
    if rag_tool_provider is not None:
        graph.add_node("researcher", make_researcher_node(rag_tool_provider))
        graph.add_edge("researcher", next_stage)
        routes["researcher"] = "researcher"

    graph.add_edge(START, "planner")
    graph.add_conditional_edges(
        "planner",
        make_route_after_planner(
            retrieval_available=rag_tool_provider is not None,
            skills_available=bool(catalog),
        ),
        routes,
    )
    graph.add_edge("outline", "writer")
    graph.add_edge("writer", "validator")
    # 校验后：继续写 / 重写 / 进入整篇校验 / 重新规划 / 汇总（含安全结束）
    graph.add_conditional_edges(
        "validator",
        make_route_after_validation(max_retries=max_retries, max_sections=max_sections),
        {
            "writer": "writer",
            "planner": "planner",
            "validator": "validator",
            "summarize": "summarizer",
        },
    )
    graph.add_edge("summarizer", END)

    return graph.compile(checkpointer=checkpointer)
