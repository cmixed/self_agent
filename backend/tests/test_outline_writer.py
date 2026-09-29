from __future__ import annotations

import pytest
from fakes import DRAFT_TEXT, OUTLINE_JSON, OUTLINE_PAYLOAD, ScriptedProvider, validation_fail_json

from app.agents.outline import MAX_SECTIONS, make_outline_node
from app.agents.writer import make_writer_node, resolve_target_index
from app.llm.base import LLMResponseFormatError
from app.models.state import initial_state


async def test_outline_node_produces_sections_and_resets_generation() -> None:
    provider = ScriptedProvider([OUTLINE_JSON])
    node = make_outline_node(provider, max_retries=0)

    state = initial_state("写一篇综述", task_id="t-outline")
    # 模拟 replan：已有旧的生成结果，应被重置
    state["sections"] = [{"title": "旧章节", "content": "旧内容"}]
    state["validation_result"] = {
        "passed": False,
        "issues": ["x"],
        "suggested_action": "replan",
        "target": "document",
    }

    update = await node(state)

    titles = [section["title"] for section in update["outline"]]
    assert titles == [section["title"] for section in OUTLINE_PAYLOAD["sections"]]
    assert all(section["content"] == "" for section in update["outline"])
    assert update["sections"] == []
    assert update["validation_result"] is None
    assert update["step_results"][0]["step_id"] == "outline"
    assert provider.json_modes == [True]


async def test_outline_node_retries_then_raises_on_bad_json() -> None:
    provider = ScriptedProvider(["坏的", "还是坏的"])
    node = make_outline_node(provider, max_retries=1)

    with pytest.raises(LLMResponseFormatError):
        await node(initial_state("x", task_id="t"))
    assert len(provider.calls) == 2


def _state_with_outline() -> dict:
    state = initial_state("写一篇综述", task_id="t-writer")
    state["outline"] = [
        {"title": "引言", "content": ""},
        {"title": "方法", "content": ""},
    ]
    return state


async def test_writer_appends_next_section_and_returns_full_list() -> None:
    provider = ScriptedProvider(["第一章正文"])
    node = make_writer_node(provider)

    first = await node(_state_with_outline())

    # sections 为覆盖语义：返回完整列表
    assert [section["title"] for section in first["sections"]] == ["引言"]
    assert first["sections"][0]["content"] == "第一章正文"
    assert first["current_step"] == "chapter_1"
    assert first["step_results"][0]["step_id"] == "chapter_1"

    # 第二次调用追加第 2 章
    state = _state_with_outline()
    state["sections"] = first["sections"]
    second = await node(state)
    assert [section["title"] for section in second["sections"]] == ["引言", "方法"]
    assert second["current_step"] == "chapter_2"


async def test_writer_rewrites_targeted_chapter() -> None:
    provider = ScriptedProvider(["修正后的第一章"])
    node = make_writer_node(provider)

    state = _state_with_outline()
    state["sections"] = [
        {"title": "引言", "content": "旧的第一章"},
        {"title": "方法", "content": "第二章"},
    ]
    state["validation_result"] = {
        "passed": False,
        "issues": ["第一章内容空泛"],
        "suggested_action": "retry_writer",
        "target": "chapter_1",
    }

    update = await node(state)

    # 重写第 1 章，章节数量不变
    assert len(update["sections"]) == 2
    assert update["sections"][0]["content"] == "修正后的第一章"
    assert update["sections"][1]["content"] == "第二章"
    assert update["current_step"] == "chapter_1"
    # 校验问题被带进重写提示词
    assert "第一章内容空泛" in provider.calls[0][1].content


async def test_writer_does_nothing_when_outline_finished() -> None:
    state = _state_with_outline()
    state["sections"] = [
        {"title": "引言", "content": DRAFT_TEXT},
        {"title": "方法", "content": DRAFT_TEXT},
    ]

    node = make_writer_node(ScriptedProvider())
    assert await node(state) == {}


def test_resolve_target_index_appends_then_rewrites() -> None:
    state = _state_with_outline()

    assert resolve_target_index(state) == (0, False)

    state["sections"] = [{"title": "引言", "content": "x"}]
    assert resolve_target_index(state) == (1, False)

    state["validation_result"] = {
        "passed": False,
        "issues": [],
        "suggested_action": "retry_writer",
        "target": "chapter_1",
    }
    assert resolve_target_index(state) == (0, True)

    # 全部写完且无需重试 -> 无内容可写
    state["sections"] = [
        {"title": "引言", "content": "x"},
        {"title": "方法", "content": "y"},
    ]
    state["validation_result"] = None
    assert resolve_target_index(state) == (None, False)


def test_resolve_target_index_respects_max_sections() -> None:
    state = initial_state("x", task_id="t")
    state["outline"] = [{"title": f"s{i}", "content": ""} for i in range(MAX_SECTIONS + 3)]
    state["sections"] = [{"title": f"s{i}", "content": "c"} for i in range(MAX_SECTIONS)]

    assert resolve_target_index(state) == (None, False)


def test_resolve_target_index_ignores_stale_retry_after_replan() -> None:
    """replan 清空 sections 后，旧的 retry 目标不应导致下标错位。"""
    state = _state_with_outline()
    state["sections"] = []  # replan 重置
    state["validation_result"] = {
        "passed": False,
        "issues": [],
        "suggested_action": "retry_writer",
        "target": "chapter_2",
    }

    assert resolve_target_index(state) == (0, False)


def test_validation_fail_json_helper_marks_failure() -> None:
    import json

    payload = json.loads(validation_fail_json("replan", ["方向不对"]))
    assert payload["passed"] is False
    assert payload["suggested_action"] == "replan"
    assert payload["issues"] == ["方向不对"]
