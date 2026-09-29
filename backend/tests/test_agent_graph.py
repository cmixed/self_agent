from __future__ import annotations

from fakes import DRAFT_TEXT, PLAN_JSON, PLAN_PAYLOAD, ScriptedProvider

from app.core.agent_graph import build_graph
from app.models.state import initial_state
from app.services.task_service import TaskService


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
