from __future__ import annotations

from fakes import ScriptedProvider, validation_fail_json

from app.agents.validator import (
    chapter_index_from_target,
    make_route_after_validation,
    make_validator_node,
    resolve_target,
)
from app.models.state import initial_state


def _state(*, chapters_written: int, outline_size: int = 2) -> dict:
    state = initial_state("写一篇综述", task_id="t-val")
    state["outline"] = [{"title": f"章节{i + 1}", "content": ""} for i in range(outline_size)]
    state["sections"] = [
        {"title": f"章节{i + 1}", "content": f"第{i + 1}章正文"} for i in range(chapters_written)
    ]
    return state


async def test_validator_validates_chapter_scope() -> None:
    node = make_validator_node(ScriptedProvider(), max_retries=0)

    update = await node(_state(chapters_written=1))

    result = update["validation_result"]
    assert result["passed"] is True
    assert result["target"] == "chapter_1"
    assert result["suggested_action"] == "continue"
    assert update["retry_count"] == 0
    assert update["step_results"][0]["step_id"] == "validate_chapter_1"


async def test_validator_validates_document_scope_when_all_chapters_done() -> None:
    node = make_validator_node(ScriptedProvider(), max_retries=0)

    update = await node(_state(chapters_written=2))

    assert update["validation_result"]["target"] == "document"
    assert update["step_results"][0]["step_id"] == "validate_document"


async def test_validator_increments_retry_count_on_failure() -> None:
    provider = ScriptedProvider([validation_fail_json("retry_writer", ["太笼统"])])
    node = make_validator_node(provider, max_retries=0)

    update = await node(_state(chapters_written=1))

    result = update["validation_result"]
    assert result["passed"] is False
    assert result["issues"] == ["太笼统"]
    assert result["suggested_action"] == "retry_writer"
    assert update["retry_count"] == 1
    assert update["step_results"][0]["status"] == "error"


async def test_validator_normalizes_contradictory_action() -> None:
    """模型返回 passed=false 却给 continue 时，按 retry_writer 处理，避免空转。"""
    import json

    payload = json.dumps({"passed": False, "issues": [], "suggested_action": "continue"})
    node = make_validator_node(ScriptedProvider([payload]), max_retries=0)

    update = await node(_state(chapters_written=1))
    assert update["validation_result"]["suggested_action"] == "retry_writer"


async def test_validator_keeps_existing_retry_count() -> None:
    node = make_validator_node(ScriptedProvider(), max_retries=0)

    state = _state(chapters_written=1)
    state["retry_count"] = 1
    update = await node(state)

    # 通过时不再累加
    assert update["retry_count"] == 1


def test_resolve_target_helper() -> None:
    target, content = resolve_target(_state(chapters_written=1))
    assert target == "chapter_1"
    assert "第1章正文" in content

    target, content = resolve_target(_state(chapters_written=2))
    assert target == "document"
    assert "第1章正文" in content and "第2章正文" in content


def test_chapter_index_from_target() -> None:
    assert chapter_index_from_target("chapter_2") == 1
    assert chapter_index_from_target("document") is None
    assert chapter_index_from_target("") is None


def test_route_after_validation_when_passed() -> None:
    route = make_route_after_validation(max_retries=2)

    # 还有章节未写 -> 继续写
    state = _state(chapters_written=1)
    state["validation_result"] = {
        "passed": True,
        "issues": [],
        "suggested_action": "continue",
        "target": "chapter_1",
    }
    assert route(state) == "writer"

    # 全部写完 -> 汇总
    done = _state(chapters_written=2)
    done["validation_result"] = {
        "passed": True,
        "issues": [],
        "suggested_action": "continue",
        "target": "document",
    }
    assert route(done) == "summarize"


def test_route_after_validation_retry_and_replan() -> None:
    route = make_route_after_validation(max_retries=2)

    retry = _state(chapters_written=1)
    retry["retry_count"] = 1
    retry["validation_result"] = {
        "passed": False,
        "issues": ["x"],
        "suggested_action": "retry_writer",
        "target": "chapter_1",
    }
    assert route(retry) == "writer"

    replan = _state(chapters_written=1)
    replan["retry_count"] = 1
    replan["validation_result"] = {
        "passed": False,
        "issues": ["方向不对"],
        "suggested_action": "replan",
        "target": "document",
    }
    assert route(replan) == "planner"


def test_route_after_validation_caps_retries() -> None:
    """超过 MAX_RETRIES 后安全结束（§16），不再重试。"""
    route = make_route_after_validation(max_retries=2)

    state = _state(chapters_written=1)
    state["retry_count"] = 2
    state["validation_result"] = {
        "passed": False,
        "issues": ["x"],
        "suggested_action": "retry_writer",
        "target": "chapter_1",
    }
    assert route(state) == "summarize"
