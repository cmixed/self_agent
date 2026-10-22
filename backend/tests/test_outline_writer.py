from __future__ import annotations

import json

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


# --- 章节上限参数化（AGENTS.md §27 安全兜底 vs 产品预算）---


async def test_outline_prompt_follows_target_sections() -> None:
    """提示词里的章节数由配置生成，与上限同源。"""
    provider = ScriptedProvider([OUTLINE_JSON])
    node = make_outline_node(provider, max_retries=0, target_sections=5, max_sections=12)

    await node(initial_state("写综述", task_id="t-prompt"))

    system_prompt = provider.calls[0][0].content
    assert "只给 1 章" in system_prompt
    assert "最多 5 章" in system_prompt


async def test_outline_truncates_extra_sections_with_visible_note() -> None:
    """模型给出超过生成上限的章节：截断并说明，而不是整单任务失败。"""
    payload = {"sections": [{"title": f"第 {i} 章"} for i in range(1, 11)]}
    provider = ScriptedProvider([json.dumps(payload, ensure_ascii=False)])
    node = make_outline_node(provider, max_retries=0, target_sections=4, max_sections=5)

    update = await node(initial_state("写综述", task_id="t-truncate"))

    assert len(update["outline"]) == 5
    assert len(update["sections"]) == 5
    summary = update["step_results"][0]["summary"]
    assert "模型给出 10 章" in summary
    assert "已按上限 5 截断" in summary


async def test_outline_within_limit_has_no_truncation_note() -> None:
    provider = ScriptedProvider([OUTLINE_JSON])  # 2 章
    node = make_outline_node(provider, max_retries=0, target_sections=6, max_sections=12)

    update = await node(initial_state("写综述", task_id="t-no-truncate"))

    assert "截断" not in update["step_results"][0]["summary"]


async def test_outline_over_schema_guard_still_retries_then_fails() -> None:
    """超过结构防爆上限（50）属于异常输出，仍按格式错误处理。"""
    from app.core.limits import SCHEMA_SECTION_GUARD

    payload = {"sections": [{"title": f"c{i}"} for i in range(SCHEMA_SECTION_GUARD + 1)]}
    provider = ScriptedProvider([json.dumps(payload, ensure_ascii=False)])
    node = make_outline_node(provider, max_retries=0, max_sections=12)

    with pytest.raises(LLMResponseFormatError):
        await node(initial_state("写综述", task_id="t-guard"))


def test_failed_chapters_respects_same_bound_as_writing() -> None:
    """失败清单与撰写边界一致：不会被写的章节不该出现在失败清单里。"""
    from app.agents.chapters import failed_chapters

    state = initial_state("x", task_id="t")
    state["outline"] = [{"title": f"s{i}", "content": ""} for i in range(15)]
    state["sections"] = [{"title": f"s{i}", "content": ""} for i in range(15)]
    state["chapter_validations"] = {
        f"chapter_{i}": {
            "passed": False,
            "issues": ["未通过"],
            "suggested_action": "retry_writer",
            "target": f"chapter_{i}",
        }
        for i in range(1, 16)
    }
    state["retry_counts"] = {f"chapter_{i}": 9 for i in range(1, 16)}

    assert failed_chapters(state, max_retries=2, max_sections=6) == list(range(6))


# --- 篇幅：软目标（字数）与截断可见性 ---


async def test_writer_prompt_includes_char_target() -> None:
    """篇幅用目标字数表达（软目标），不做 max_tokens 硬截断。"""
    provider = ScriptedProvider(default_text="正文")
    node = make_writer_node(provider, max_retries=0, target_total_chars=6000)
    state = _state_with_outline()
    state["outline"] = [{"title": "引言", "content": ""}, {"title": "方法", "content": ""}]
    state["sections"] = [{"title": "引言", "content": ""}, {"title": "方法", "content": ""}]

    await node(state)

    user_prompt = provider.calls[0][1].content
    assert "本章目标篇幅：约 2400-3900 字" in user_prompt  # 6000/2 分摊后区间


async def test_writer_continues_once_when_truncated() -> None:
    """输出被长度上限截断：追加一次有限续写，内容拼接、不整单失败。"""
    provider = ScriptedProvider(
        ["前半段正文……", "续写的后半段。"],
        finish_reasons=["length", "stop"],
    )
    node = make_writer_node(provider, max_retries=0)
    state = _state_with_outline()

    update = await node(state)

    assert len(provider.calls) == 2  # 只续写一次
    content = update["sections"][0]["content"]
    assert "前半段正文" in content
    assert "续写的后半段" in content
    assert "截断" not in update["step_results"][0]["summary"]
    # 续写请求要带上已写结尾并要求“不要重复”
    assert "不要重复已写内容" in provider.calls[1][1].content


async def test_writer_marks_persistent_truncation() -> None:
    """续写后仍然截断：事实必须可见（step_result 标注），但不让整单失败。"""
    provider = ScriptedProvider(
        ["第一段", "又被截断的一段"],
        finish_reasons=["length", "length"],
    )
    node = make_writer_node(provider, max_retries=0)
    state = _state_with_outline()

    update = await node(state)

    summary = update["step_results"][0]["summary"]
    assert "截断" in summary
    assert update["step_results"][0]["status"] == "error"


async def test_writer_no_continuation_without_truncation() -> None:
    provider = ScriptedProvider(["完整的一章"], finish_reasons=["stop"])
    node = make_writer_node(provider, max_retries=0)

    await node(_state_with_outline())

    assert len(provider.calls) == 1


async def test_validator_input_includes_char_target() -> None:
    from app.agents.validator import make_validator_node

    provider = ScriptedProvider()  # 默认返回通过
    node = make_validator_node(provider, max_retries=0, target_total_chars=6000)
    state = _state_with_outline()
    state["sections"] = [
        {"title": "引言", "content": "内容一"},
        {"title": "方法", "content": "内容二"},
    ]

    await node(state)

    user_prompt = provider.calls[0][1].content
    assert "目标篇幅（本章）：约 2400-3900 字" in user_prompt
    assert "当前实际" in user_prompt
