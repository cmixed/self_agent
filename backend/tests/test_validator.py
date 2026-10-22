from __future__ import annotations

import json

from fakes import ScriptedProvider, validation_fail_json

from app.agents.validator import (
    make_route_after_validation,
    make_validator_node,
    resolve_scope,
)
from app.models.state import initial_state


def _state(*, outline: int = 2, written: list[int], retry_counts=None, validations=None) -> dict:
    state = initial_state("写一篇综述", task_id="t-val")
    state["outline"] = [{"title": f"章节{i + 1}", "content": ""} for i in range(outline)]
    state["sections"] = [
        {"title": f"章节{i + 1}", "content": (f"第{i + 1}章正文" if i in written else "")}
        for i in range(outline)
    ]
    state["retry_counts"] = retry_counts or {}
    state["chapter_validations"] = validations or {}
    return state


# --- 范围判定 ---


def test_resolve_scope_chapter_when_more_to_write() -> None:
    scope, index = resolve_scope(_state(written=[0]), max_retries=2)
    assert (scope, index) == ("chapter", 0)


def test_resolve_scope_document_when_all_chapters_passed() -> None:
    validations = {
        "chapter_1": {
            "passed": True,
            "issues": [],
            "suggested_action": "continue",
            "target": "chapter_1",
        },
        "chapter_2": {
            "passed": True,
            "issues": [],
            "suggested_action": "continue",
            "target": "chapter_2",
        },
    }
    scope, index = resolve_scope(_state(written=[0, 1], validations=validations), max_retries=2)
    assert (scope, index) == ("document", None)


def test_resolve_scope_document_without_outline() -> None:
    state = initial_state("x", task_id="t")
    assert resolve_scope(state, max_retries=2) == ("document", None)


# --- 节点行为 ---


async def test_validator_validates_chapter_and_keeps_pass_count() -> None:
    node = make_validator_node(ScriptedProvider(), max_retries=0)

    update = await node(_state(written=[0]))

    result = update["validation_result"]
    assert result["target"] == "chapter_1"
    assert result["passed"] is True
    assert update["retry_counts"] == {}
    assert update["retry_count"] == 0
    assert update["chapter_validations"]["chapter_1"]["passed"] is True
    assert update["step_results"][0]["step_id"] == "validate_chapter_1"


async def test_validator_increments_chapter_retry_budget() -> None:
    provider = ScriptedProvider([validation_fail_json("retry_writer", ["太笼统"])])
    node = make_validator_node(provider, max_retries=2)

    update = await node(_state(written=[0]))

    assert update["retry_counts"] == {"chapter_1": 1}
    assert update["retry_count"] == 0  # replan 计数不受影响
    assert update["validation_result"]["suggested_action"] == "retry_writer"
    assert update["step_results"][0]["status"] == "error"


async def test_validator_marks_exhausted_chapter_in_summary() -> None:
    provider = ScriptedProvider([validation_fail_json("retry_writer")])
    node = make_validator_node(provider, max_retries=1)

    update = await node(_state(written=[0]))

    assert update["retry_counts"] == {"chapter_1": 1}
    assert "已达重试上限" in update["step_results"][0]["summary"]


async def test_validator_counts_replan_globally() -> None:
    provider = ScriptedProvider([validation_fail_json("replan", ["计划不合理"])])
    node = make_validator_node(provider, max_retries=2)

    update = await node(_state(written=[0]))

    assert update["retry_count"] == 1
    assert update["retry_counts"] == {}  # replan 不占用章节预算
    assert update["validation_result"]["suggested_action"] == "replan"


async def test_validator_escalates_document_retry_to_replan() -> None:
    """整篇校验无法定位到具体章节，retry_writer 升级为 replan。"""
    validations = {
        "chapter_1": {
            "passed": True,
            "issues": [],
            "suggested_action": "continue",
            "target": "chapter_1",
        }
    }
    provider = ScriptedProvider([validation_fail_json("retry_writer", ["整体重复"])])
    node = make_validator_node(provider, max_retries=2)

    update = await node(_state(outline=1, written=[0], validations=validations))

    assert update["validation_result"]["target"] == "document"
    assert update["validation_result"]["suggested_action"] == "replan"
    assert update["retry_count"] == 1


async def test_validator_normalizes_contradictory_action() -> None:
    payload = json.dumps({"passed": False, "issues": [], "suggested_action": "continue"})
    node = make_validator_node(ScriptedProvider([payload]), max_retries=1)

    update = await node(_state(written=[0]))
    assert update["validation_result"]["suggested_action"] == "retry_writer"
    assert update["retry_counts"] == {"chapter_1": 1}


# --- 路由 ---


def _route_state(
    *,
    passed: bool,
    action: str,
    target: str,
    written: list[int],
    outline: int = 2,
    retry_counts=None,
    validations=None,
    replan_count: int = 0,
) -> dict:
    state = _state(
        outline=outline,
        written=written,
        retry_counts=retry_counts,
        validations=validations,
    )
    state["retry_count"] = replan_count
    state["validation_result"] = {
        "passed": passed,
        "issues": [],
        "suggested_action": action,
        "target": target,
    }
    return state


def test_route_writes_next_chapter_after_pass() -> None:
    route = make_route_after_validation(max_retries=2)
    state = _route_state(passed=True, action="continue", target="chapter_1", written=[0])
    assert route(state) == "writer"


def test_route_enters_document_check_after_last_chapter() -> None:
    route = make_route_after_validation(max_retries=2)
    validations = {
        "chapter_1": {
            "passed": True,
            "issues": [],
            "suggested_action": "continue",
            "target": "chapter_1",
        },
        "chapter_2": {
            "passed": True,
            "issues": [],
            "suggested_action": "continue",
            "target": "chapter_2",
        },
    }
    state = _route_state(
        passed=True,
        action="continue",
        target="chapter_2",
        written=[0, 1],
        validations=validations,
    )
    assert route(state) == "validator"


def test_route_summarizes_after_document_pass() -> None:
    route = make_route_after_validation(max_retries=2)
    state = _route_state(passed=True, action="continue", target="document", written=[0, 1])
    assert route(state) == "summarize"


def test_route_rewrites_chapter_within_budget() -> None:
    route = make_route_after_validation(max_retries=2)
    state = _route_state(
        passed=False,
        action="retry_writer",
        target="chapter_1",
        written=[0],
        retry_counts={"chapter_1": 1},
    )
    assert route(state) == "writer"


def test_route_skips_exhausted_chapter_and_continues() -> None:
    """章节达上限后不影响其他章节，继续写下一章。"""
    route = make_route_after_validation(max_retries=1)
    state = _route_state(
        passed=False,
        action="retry_writer",
        target="chapter_1",
        written=[0],
        retry_counts={"chapter_1": 1},
    )
    assert route(state) == "writer"


def test_route_document_check_after_exhausted_last_chapter() -> None:
    route = make_route_after_validation(max_retries=1)
    state = _route_state(
        passed=False,
        action="retry_writer",
        target="chapter_2",
        written=[0, 1],
        retry_counts={"chapter_2": 1},
    )
    assert route(state) == "validator"


def test_route_replans_within_budget() -> None:
    route = make_route_after_validation(max_retries=2)
    state = _route_state(
        passed=False,
        action="replan",
        target="document",
        written=[0],
        replan_count=1,
    )
    assert route(state) == "planner"


def test_route_does_not_replan_beyond_budget() -> None:
    route = make_route_after_validation(max_retries=2)
    state = _route_state(
        passed=False,
        action="replan",
        target="document",
        written=[0, 1],
        replan_count=2,
    )
    assert route(state) == "summarize"


def test_route_chapter_replans_do_not_loop_forever() -> None:
    """章节级 replan 超预算后不再回 planner，而是继续处理章节。"""
    route = make_route_after_validation(max_retries=2)
    state = _route_state(
        passed=False,
        action="replan",
        target="chapter_1",
        written=[0],
        replan_count=2,
    )
    # 超预算：不再 replan；该章仍有预算（retry_counts 空）-> 重写
    assert route(state) == "writer"


async def test_validator_downgrades_replan_when_budget_exhausted() -> None:
    """预算耗尽时校验节点必须降级 replan 动作，避免路由回 planner 空转。"""
    validations = {
        "chapter_1": {
            "passed": True,
            "issues": [],
            "suggested_action": "continue",
            "target": "chapter_1",
        }
    }
    state = _state(outline=1, written=[0], validations=validations)
    state["retry_count"] = 1
    provider = ScriptedProvider([validation_fail_json("replan", ["计划不合理"])])
    node = make_validator_node(provider, max_retries=1)

    update = await node(state)

    assert update["retry_count"] == 1
    assert update["validation_result"]["suggested_action"] == "continue"
    route = make_route_after_validation(max_retries=1)
    assert route({**state, **update}) == "summarize"
