"""LangGraph 工作流编排。

只负责节点连接与条件路由，业务逻辑在 ``app/agents/`` 中（见 AGENTS.md §4.2）。

当前拓扑：

    START → planner ──(需要检索)──→ researcher ──→ writer → summarizer → END
                  │                    ↑
                  ├──(不需要检索)──────┘
                  └──(无计划)────→ END

Phase 4 会在 writer 之后插入 validator 与有限重试；扩展均为增量插入。
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.planner import make_planner_node, make_route_after_planner
from app.agents.researcher import make_researcher_node
from app.agents.summarizer import summarizer_node
from app.agents.writer import make_writer_node
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
    graph.add_node("writer", make_writer_node(llm))
    graph.add_node("summarizer", summarizer_node)

    routes: dict[str, str] = {"writer": "writer", "end": END}
    if rag_tool_provider is not None:
        graph.add_node("researcher", make_researcher_node(rag_tool_provider))
        graph.add_edge("researcher", "writer")
        routes["researcher"] = "researcher"

    graph.add_edge(START, "planner")
    graph.add_conditional_edges(
        "planner",
        make_route_after_planner(retrieval_available=rag_tool_provider is not None),
        routes,
    )
    graph.add_edge("writer", "summarizer")
    graph.add_edge("summarizer", END)

    return graph.compile()
