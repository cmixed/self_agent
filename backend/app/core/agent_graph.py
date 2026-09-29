"""LangGraph 工作流编排。

只负责节点连接与条件路由，业务逻辑在 ``app/agents/`` 中（见 AGENTS.md §4.2）。

当前拓扑（Phase 4A）：

    START → planner ──(需要检索)──→ researcher ──┐
                  │                             ↓
                  ├──(不需要检索)──────────→ outline → writer ──(还有章节)──┐
                  │                                    ↑                   │
                  │                                    └───────────────────┘
                  │                                    │
                  │                            (章节写完) ↓
                  └──(无计划)──→ END          summarizer → END

Phase 4B 会在 writer 之后、summarizer 之前插入 validator 与有限重试。
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.outline import make_outline_node
from app.agents.planner import make_planner_node, make_route_after_planner
from app.agents.researcher import make_researcher_node
from app.agents.summarizer import summarizer_node
from app.agents.writer import make_writer_node, route_after_writer
from app.llm.base import LLMProvider
from app.models.state import AgentState
from app.rag.tools import RagTool


def build_graph(
    llm: LLMProvider,
    *,
    rag_tool_provider: Callable[[], RagTool] | None = None,
    max_retries: int = 2,
) -> CompiledStateGraph:
    """构建并编译 Agent 图。

    未提供 ``rag_tool_provider`` 时不挂载 researcher 节点，退化为不含检索的流程
    （便于测试与无知识库场景）。
    """
    graph = StateGraph(AgentState)

    graph.add_node("planner", make_planner_node(llm, max_retries=max_retries))
    graph.add_node("outline", make_outline_node(llm, max_retries=max_retries))
    graph.add_node("writer", make_writer_node(llm))
    graph.add_node("summarizer", summarizer_node)

    routes: dict[str, str] = {"outline": "outline", "end": END}
    if rag_tool_provider is not None:
        graph.add_node("researcher", make_researcher_node(rag_tool_provider))
        graph.add_edge("researcher", "outline")
        routes["researcher"] = "researcher"

    graph.add_edge(START, "planner")
    graph.add_conditional_edges(
        "planner",
        make_route_after_planner(retrieval_available=rag_tool_provider is not None),
        routes,
    )
    graph.add_edge("outline", "writer")
    # 逐章循环：还有章节就回到 writer，否则汇总
    graph.add_conditional_edges(
        "writer",
        route_after_writer,
        {"writer": "writer", "summarize": "summarizer"},
    )
    graph.add_edge("summarizer", END)

    return graph.compile()
