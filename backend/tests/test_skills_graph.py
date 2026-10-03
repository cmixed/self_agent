"""技能（skill）在 Agent 中的集成测试。

全部使用假 Provider，不依赖真实 API（AGENTS.md §22）。
"""

from __future__ import annotations

import json

from fakes import OUTLINE_JSON, ScriptedProvider, validation_fail_json

from app.agents.skills import (
    MAX_SKILL_STEPS,
    make_route_after_skills,
    make_skills_node,
    pending_skill_step,
    render_skill_outputs,
)
from app.core.agent_graph import build_graph
from app.models.state import AgentState, Plan, initial_state
from app.services.task_service import TaskService

CATALOG = [
    {
        "skill_id": "builtin-compare",
        "name": "对比分析",
        "description": "比较多个方案时使用",
        "content": "请做结构化对比分析。",
    },
    {
        "skill_id": "builtin-takeaways",
        "name": "要点提炼",
        "description": "提炼核心要点时使用",
        "content": "请提炼核心要点。",
    },
]


def _state_with_plan(steps: list[dict], *, skill_outputs: list[dict] | None = None) -> AgentState:
    state = initial_state("写一篇综述", task_id="t1")
    state["plan"] = Plan(goal="写综述", needs_retrieval=False, steps=steps)  # type: ignore[typeddict-item]
    state["skill_outputs"] = skill_outputs or []  # type: ignore[typeddict-item]
    return state


def test_pending_skill_step_returns_first_unfinished() -> None:
    steps = [
        {"id": "s1", "type": "skill", "description": "对比", "skill_id": "builtin-compare"},
        {"id": "s2", "type": "skill", "description": "提炼", "skill_id": "builtin-takeaways"},
    ]
    state = _state_with_plan(steps)
    assert pending_skill_step(state)["id"] == "s1"  # type: ignore[index]

    state["skill_outputs"] = [  # type: ignore[typeddict-item]
        {
            "skill_id": "builtin-compare",
            "skill_name": "对比分析",
            "step_id": "s1",
            "summary": "",
            "content": "",
        }
    ]
    assert pending_skill_step(state)["id"] == "s2"  # type: ignore[index]


def test_pending_skill_step_none_when_no_skill_or_all_done() -> None:
    assert pending_skill_step(initial_state("任务", task_id="t1")) is None

    steps = [{"id": "s1", "type": "skill", "description": "对比", "skill_id": "builtin-compare"}]
    state = _state_with_plan(steps)
    state["skill_outputs"] = [  # type: ignore[typeddict-item]
        {
            "skill_id": "builtin-compare",
            "skill_name": "对比分析",
            "step_id": "s1",
            "summary": "",
            "content": "",
        }
    ]
    assert pending_skill_step(state) is None


def test_route_after_skills_loops_then_leaves() -> None:
    route = make_route_after_skills()
    assert route(initial_state("任务", task_id="t1")) == "outline"

    steps = [{"id": "s1", "type": "skill", "description": "对比", "skill_id": "builtin-compare"}]
    assert route(_state_with_plan(steps)) == "skills"


def test_render_skill_outputs_renders_blocks() -> None:
    state = initial_state("任务", task_id="t1")
    assert render_skill_outputs(state) == ""

    state["skill_outputs"] = [  # type: ignore[typeddict-item]
        {
            "skill_id": "builtin-compare",
            "skill_name": "对比分析",
            "step_id": "s1",
            "summary": "结论摘要",
            "content": "维度一：……",
        }
    ]
    rendered = render_skill_outputs(state)
    assert "对比分析" in rendered
    assert "维度一" in rendered


async def test_skills_node_produces_output() -> None:
    provider = ScriptedProvider(default_text="对比结论正文")
    node = make_skills_node(provider, CATALOG)
    steps = [{"id": "s1", "type": "skill", "description": "对比", "skill_id": "builtin-compare"}]

    update = await node(_state_with_plan(steps))

    outputs = update["skill_outputs"]
    assert outputs[0]["skill_id"] == "builtin-compare"
    assert outputs[0]["skill_name"] == "对比分析"
    assert outputs[0]["content"] == "对比结论正文"
    assert update["current_step"] == "s1"
    # 技能指令作为 system 注入，任务与资料作为 user 输入
    assert provider.calls[0][0].content == "请做结构化对比分析。"


async def test_skills_node_skips_unknown_skill() -> None:
    provider = ScriptedProvider()
    node = make_skills_node(provider, CATALOG)
    steps = [{"id": "s1", "type": "skill", "description": "未知", "skill_id": "ghost"}]

    update = await node(_state_with_plan(steps))

    assert update["step_results"][0]["status"] == "error"
    assert provider.calls == []


async def test_planner_drops_unknown_and_excess_skill_steps() -> None:
    plan = {
        "goal": "写综述",
        "needs_retrieval": False,
        "steps": [
            {"id": "s1", "type": "skill", "description": "对比", "skill_id": "builtin-compare"},
            {"id": "s2", "type": "skill", "description": "提炼", "skill_id": "builtin-takeaways"},
            {"id": "s3", "type": "skill", "description": "幽灵", "skill_id": "ghost"},
            {"id": "s4", "type": "skill", "description": "超限", "skill_id": "builtin-compare"},
            {"id": "w1", "type": "writing", "description": "撰写"},
        ],
    }
    provider = ScriptedProvider(
        [json.dumps(plan, ensure_ascii=False), "对比结论", "提炼结论", OUTLINE_JSON],
        default_text="正文",
    )
    graph = build_graph(provider, skill_catalog=CATALOG, max_retries=0)

    final = await graph.ainvoke(initial_state("写综述", task_id="t1"))

    skill_steps = [step for step in final["plan"]["steps"] if step["type"] == "skill"]
    assert len(skill_steps) == MAX_SKILL_STEPS
    assert {step["skill_id"] for step in skill_steps} == {"builtin-compare", "builtin-takeaways"}


async def test_graph_runs_skills_between_planner_and_outline() -> None:
    plan = {
        "goal": "写综述",
        "needs_retrieval": False,
        "steps": [
            {"id": "s1", "type": "skill", "description": "对比", "skill_id": "builtin-compare"},
            {"id": "w1", "type": "writing", "description": "撰写"},
        ],
    }
    provider = ScriptedProvider(
        [json.dumps(plan, ensure_ascii=False), "对比结论", OUTLINE_JSON],
        default_text="正文内容",
    )
    graph = build_graph(provider, skill_catalog=CATALOG, max_retries=0)

    events: list[str] = []
    async for event in graph.astream_events(initial_state("写综述", task_id="t1"), version="v2"):
        if event.get("event") == "on_chain_start" and isinstance(event.get("name"), str):
            events.append(event["name"])

    assert "skills" in events
    assert events.index("planner") < events.index("skills") < events.index("outline")


async def test_stream_emits_skill_events() -> None:
    plan = {
        "goal": "写综述",
        "needs_retrieval": False,
        "steps": [
            {"id": "s1", "type": "skill", "description": "对比", "skill_id": "builtin-compare"},
            {"id": "w1", "type": "writing", "description": "撰写"},
        ],
    }
    provider = ScriptedProvider(
        [json.dumps(plan, ensure_ascii=False), "对比结论", OUTLINE_JSON],
        default_text="正文内容",
    )
    service = TaskService(provider, skill_catalog=CATALOG, max_retries=0)

    events = [event async for event in service.stream("写综述")]

    names = [event["event"] for event in events]
    assert names[-1] == "task_completed"
    assert "skill_started" in names
    assert "skill_completed" in names
    started = next(event for event in events if event["event"] == "skill_started")
    completed = next(event for event in events if event["event"] == "skill_completed")
    assert started["skill_name"] == "对比分析"
    assert completed["skill_name"] == "对比分析"
    assert completed["summary"]
    assert names.index("skill_started") < names.index("skill_completed")


async def test_no_catalog_keeps_original_topology() -> None:
    """未提供技能目录时行为不变：plan 中的 skill 步骤被剔除。"""
    plan = {
        "goal": "写综述",
        "needs_retrieval": False,
        "steps": [
            {"id": "s1", "type": "skill", "description": "对比", "skill_id": "builtin-compare"},
            {"id": "w1", "type": "writing", "description": "撰写"},
        ],
    }
    provider = ScriptedProvider(
        [json.dumps(plan, ensure_ascii=False), OUTLINE_JSON],
        default_text="正文内容",
    )
    service = TaskService(provider, max_retries=0)
    events = [event async for event in service.stream("写综述")]

    assert all(event["event"] not in {"skill_started", "skill_completed"} for event in events)
    assert events[-1]["event"] == "task_completed"


async def test_validation_failure_does_not_rerun_skills() -> None:
    """校验失败重试只重写章节，不重复执行技能（技能产出在状态中复用）。"""
    plan = {
        "goal": "写综述",
        "needs_retrieval": False,
        "steps": [
            {"id": "s1", "type": "skill", "description": "对比", "skill_id": "builtin-compare"},
            {"id": "w1", "type": "writing", "description": "撰写"},
        ],
    }
    provider = ScriptedProvider(
        [
            json.dumps(plan, ensure_ascii=False),
            "对比结论",
            OUTLINE_JSON,
            "第一章草稿",
            validation_fail_json("retry_writer"),
            "第一章重写",
        ],
        default_text="草稿",
    )
    service = TaskService(provider, skill_catalog=CATALOG, max_retries=1)
    events = [event async for event in service.stream("写综述")]

    assert [event["event"] for event in events].count("skill_started") == 1
