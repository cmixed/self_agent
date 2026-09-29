"""LangGraph 工作流编排。

只负责节点连接与条件路由，业务逻辑在 ``app/agents/`` 中（见 AGENTS.md §4.2）。

Phase 2 拓扑：

    START → planner ──(有计划)──→ writer → summarizer → END
                  └──(无计划)────→ END

Phase 3 在 planner 之后插入 researcher；Phase 4 在 writer 之后插入 validator
与有限重试。后续扩展均为增量插入，不改动已有边。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.planner import make_planner_node, route_after_planner
from app.agents.summarizer import summarizer_node
from app.agents.writer import make_writer_node
from app.llm.base import LLMProvider
from app.models.state import AgentState


def build_graph(llm: LLMProvider, *, max_retries: int = 2) -> CompiledStateGraph:
    """构建并编译 Agent 图。"""
    graph = StateGraph(AgentState)

    graph.add_node("planner", make_planner_node(llm, max_retries=max_retries))
    graph.add_node("writer", make_writer_node(llm))
    graph.add_node("summarizer", summarizer_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {"writer": "writer", "end": END},
    )
    graph.add_edge("writer", "summarizer")
    graph.add_edge("summarizer", END)

    return graph.compile()
