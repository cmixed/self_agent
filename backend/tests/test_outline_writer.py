from __future__ import annotations

import pytest
from fakes import (
    DRAFT_TEXT,
    OUTLINE_JSON,
    OUTLINE_PAYLOAD,
    ScriptedProvider,
    validation_fail_json,
)

from app.agents.chapters import MAX_SECTIONS
from app.agents.outline import make_outline_node
from app.agents.writer import make_writer_node, resolve_target_index
from app.llm.base import LLMResponseFormatError
from app.models.state import initial_state

MAX_RETRIES = 2


async def test_outline_prefills_aligned_sections_and_resets_state() -> None:
    provider = ScriptedProvider([OUTLINE_JSON])
    node = make_outline_node(provider, max_retries=0)

    state = initial_state("写一篇综述", task_id="t-outline")
    # 模拟 replan：旧的生成/校验结果都应被重置
    state["sections"] = [{"title": "旧章节", "content": "旧内容"}]
    state["retry_counts"] = {"chapter_1": 2}
    state["chapter_validations"] = {"chapter_1": {"passed": False}}
    state["validation_result"] = {
        "passed": False,
        "issues": ["x"],
        "suggested_action": "replan",
        "target": "document",
    }

    update = await node(state)

    titles = [section["title"] for section in update["outline"]]
    assert titles == [section["title"] for section in OUTLINE_PAYLOAD["sections"]]
    # sections 与 outline 对齐且为占位（空内容）
    assert [section["title"] for section in update["sections"]] == titles
    assert all(section["content"] == "" for section in update["sections"])
    assert len(update["sections"]) == len(update["outline"])
    assert update["retry_counts"] == {}
    assert update["chapter_validations"] == {}
    assert update["validation_result"] is None
    assert provider.json_modes == [True]


async def test_outline_retries_then_raises_on_bad_json() -> None:
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
    state["sections"] = [
        {"title": "引言", "content": ""},
        {"title": "方法", "content": ""},
    ]
    return state


async def test_writer_fills_next_pending_chapter() -> None:
    node = make_writer_node(ScriptedProvider(["第一章正文"]), max_retries=MAX_RETRIES)

    update = await node(_state_with_outline())

    assert len(update["sections"]) == 2  # 与 outline 对齐
    assert update["sections"][0]["content"] == "第一章正文"
    assert update["sections"][1]["content"] == ""
    assert update["current_step"] == "chapter_1"
    assert update["step_results"][0]["step_id"] == "chapter_1"


async def test_writer_moves_to_next_chapter() -> None:
    state = _state_with_outline()
    state["sections"][0]["content"] = "第一章"
    state["chapter_validations"] = {
        "chapter_1": {
            "passed": True,
            "issues": [],
            "suggested_action": "continue",
            "target": "chapter_1",
        }
    }
    node = make_writer_node(ScriptedProvider(["第二章正文"]), max_retries=MAX_RETRIES)

    update = await node(state)

    assert update["sections"][0]["content"] == "第一章"
    assert update["sections"][1]["content"] == "第二章正文"
    assert update["current_step"] == "chapter_2"


async def test_writer_rewrites_targeted_chapter_with_issues() -> None:
    provider = ScriptedProvider(["修正后的第一章"])
    node = make_writer_node(provider, max_retries=MAX_RETRIES)

    state = _state_with_outline()
    state["sections"][0]["content"] = "旧的第一章"
    state["sections"][1]["content"] = "第二章"
    state["validation_result"] = {
        "passed": False,
        "issues": ["第一章内容空泛"],
        "suggested_action": "retry_writer",
        "target": "chapter_1",
    }
    state["retry_counts"] = {"chapter_1": 1}
    state["chapter_validations"] = {"chapter_1": state["validation_result"]}

    update = await node(state)

    assert update["sections"][0]["content"] == "修正后的第一章"
    assert update["sections"][1]["content"] == "第二章"  # 不影响其他章节
    assert update["current_step"] == "chapter_1"
    assert "第一章内容空泛" in provider.calls[0][1].content


async def test_writer_skips_exhausted_chapter_and_continues() -> None:
    """某章达重试上限后跳过该章，继续写下一章。"""
    node = make_writer_node(ScriptedProvider(["第二章正文"]), max_retries=1)

    state = _state_with_outline()
    state["sections"][0]["content"] = "失败的第一章"
    state["retry_counts"] = {"chapter_1": 1}
    state["chapter_validations"] = {
        "chapter_1": {
            "passed": False,
            "issues": ["太差"],
            "suggested_action": "retry_writer",
            "target": "chapter_1",
        }
    }
    state["validation_result"] = state["chapter_validations"]["chapter_1"]

    update = await node(state)

    # 不重写第 1 章，而是写第 2 章
    assert update["sections"][0]["content"] == "失败的第一章"
    assert update["sections"][1]["content"] == "第二章正文"
    assert update["current_step"] == "chapter_2"


async def test_writer_does_nothing_when_all_chapters_done() -> None:
    state = _state_with_outline()
    state["sections"] = [
        {"title": "引言", "content": DRAFT_TEXT},
        {"title": "方法", "content": DRAFT_TEXT},
    ]
    node = make_writer_node(ScriptedProvider(), max_retries=MAX_RETRIES)

    assert await node(state) == {}


def test_resolve_target_index_variants() -> None:
    state = _state_with_outline()
    assert resolve_target_index(state, max_retries=MAX_RETRIES) == (0, False)

    state["sections"][0]["content"] = "x"
    assert resolve_target_index(state, max_retries=MAX_RETRIES) == (1, False)

    state["validation_result"] = {
        "passed": False,
        "issues": [],
        "suggested_action": "retry_writer",
        "target": "chapter_1",
    }
    assert resolve_target_index(state, max_retries=MAX_RETRIES) == (0, True)

    # 该章预算耗尽 -> 不再重写
    state["retry_counts"] = {"chapter_1": MAX_RETRIES}
    assert resolve_target_index(state, max_retries=MAX_RETRIES) == (1, False)


def test_resolve_target_index_ignores_stale_retry_after_replan() -> None:
    state = _state_with_outline()
    state["sections"] = [
        {"title": "引言", "content": ""},
        {"title": "方法", "content": ""},
    ]
    state["validation_result"] = {
        "passed": False,
        "issues": [],
        "suggested_action": "retry_writer",
        "target": "chapter_2",
    }
    assert resolve_target_index(state, max_retries=MAX_RETRIES) == (0, False)


def test_resolve_target_index_respects_max_sections() -> None:
    state = initial_state("x", task_id="t")
    state["outline"] = [{"title": f"s{i}", "content": ""} for i in range(MAX_SECTIONS + 3)]
    state["sections"] = [{"title": f"s{i}", "content": "c"} for i in range(MAX_SECTIONS)]
    # 超出 MAX_SECTIONS 的章节不会被继续写入（防止无界循环）
    assert resolve_target_index(state, max_retries=MAX_RETRIES) == (None, False)


def test_validation_fail_json_helper_marks_failure() -> None:
    import json

    payload = json.loads(validation_fail_json("replan", ["方向不对"]))
    assert payload["passed"] is False
    assert payload["suggested_action"] == "replan"
    assert payload["issues"] == ["方向不对"]
