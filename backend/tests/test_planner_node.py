from __future__ import annotations

import pytest
from fakes import PLAN_JSON, PLAN_PAYLOAD, ScriptedProvider

from app.agents.planner import make_planner_node, route_after_planner
from app.llm.base import LLMResponseFormatError
from app.models.state import initial_state


async def test_planner_produces_structured_plan() -> None:
    provider = ScriptedProvider([PLAN_JSON])
    node = make_planner_node(provider, max_retries=0)

    update = await node(initial_state("写一篇 RAG 综述", task_id="t-plan"))

    assert update["plan"]["goal"] == PLAN_PAYLOAD["goal"]
    assert update["plan"]["needs_retrieval"] is True
    assert [step["id"] for step in update["plan"]["steps"]] == ["research", "write"]
    assert update["current_step"] == "research"
    assert update["task_status"] == "writing"
    # 结构化输出必须走 JSON 模式
    assert provider.json_modes == [True]


async def test_planner_retries_then_raises_on_invalid_json() -> None:
    provider = ScriptedProvider(["这不是 JSON", "这也不是 JSON"])
    node = make_planner_node(provider, max_retries=1)

    with pytest.raises(LLMResponseFormatError):
        await node(initial_state("x", task_id="t-bad"))

    # 首次 + 1 次重试 = 2 次调用，有限重试不会无限循环
    assert len(provider.calls) == 2


def test_route_after_planner() -> None:
    from app.agents.planner import make_route_after_planner

    no_plan: dict = {}
    no_retrieval = {"plan": {"goal": "g", "needs_retrieval": False, "steps": []}}
    needs_retrieval = {"plan": {"goal": "g", "needs_retrieval": True, "steps": []}}

    assert route_after_planner(no_plan) == "end"  # type: ignore[arg-type]
    assert route_after_planner(no_retrieval) == "writer"  # type: ignore[arg-type]
    assert route_after_planner(needs_retrieval) == "researcher"  # type: ignore[arg-type]
    # 无检索能力时退化为直接写作
    degraded = make_route_after_planner(retrieval_available=False)
    assert degraded(needs_retrieval) == "writer"  # type: ignore[arg-type]
