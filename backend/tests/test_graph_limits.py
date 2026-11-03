from __future__ import annotations

from typing import Any

from fakes import OUTLINE_JSON, PLAN_JSON, ScriptedProvider
from langgraph.errors import GraphRecursionError

from app.agents.skills import MAX_SKILL_STEPS
from app.core.agent_graph import recursion_limit
from app.core.limits import DEFAULT_MAX_SECTIONS, HARD_SECTION_CEILING
from app.services.task_service import TaskService


def test_recursion_limit_covers_worst_case() -> None:
    """上界必须显著高于实际可能用到的超步数（否则会误中断，见真实用例）。"""
    for sections in (DEFAULT_MAX_SECTIONS, HARD_SECTION_CEILING):
        for retries in (0, 1, 2, 5):
            # 单次 pass 的最坏超步：3 个前置节点 + 技能步骤(逐个执行 + 收尾路由)
            # + 每章(1 写 + R 次重写)*2 + 整篇校验 + 汇总
            per_pass = 3 + (MAX_SKILL_STEPS + 1) + 2 * sections * (1 + retries) + 2
            assert recursion_limit(retries, max_sections=sections) > (retries + 1) * per_pass


def test_recursion_limit_scales_with_section_budget() -> None:
    assert recursion_limit(1, max_sections=6) < recursion_limit(1, max_sections=12)
    at_ceiling = recursion_limit(1, max_sections=HARD_SECTION_CEILING)
    assert at_ceiling > recursion_limit(1, max_sections=12)


def test_recursion_limit_is_increasing() -> None:
    assert recursion_limit(0) < recursion_limit(1) < recursion_limit(2)


class _RecursionBomb:
    """假的图：模拟超出 LangGraph 超步上限。"""

    async def astream_events(self, state: Any, **kwargs: Any):
        raise GraphRecursionError("Recursion limit of 25 reached")
        yield  # pragma: no cover - 使其成为 async generator


async def test_stream_reports_recursion_limit_as_task_failed() -> None:
    service = TaskService(ScriptedProvider([PLAN_JSON, OUTLINE_JSON]), max_retries=1)
    service._graph = _RecursionBomb()  # type: ignore[assignment]

    events = [event async for event in service.stream("写一篇综述")]

    assert events[-1]["event"] == "task_failed"
    assert events[-1]["error_type"] == "graph_recursion_limit"
    assert "安全上限" in events[-1]["message"]


class _InternalErrorGraph:
    async def astream_events(self, state: Any, **kwargs: Any):
        raise RuntimeError("boom")
        yield  # pragma: no cover


async def test_stream_hides_internal_error_details() -> None:
    service = TaskService(ScriptedProvider([PLAN_JSON, OUTLINE_JSON]), max_retries=1)
    service._graph = _InternalErrorGraph()  # type: ignore[assignment]

    events = [event async for event in service.stream("写一篇综述")]

    assert events[-1]["event"] == "task_failed"
    assert events[-1]["error_type"] == "internal_error"
    assert "boom" not in events[-1]["message"]


def test_service_passes_recursion_limit_config() -> None:
    service = TaskService(ScriptedProvider(), max_retries=3)
    assert service._config_for("t").get("recursion_limit") == recursion_limit(3)
