from __future__ import annotations

import pytest
from fakes import DRAFT_TEXT, OUTLINE_JSON, OUTLINE_PAYLOAD, ScriptedProvider

from app.agents.outline import MAX_SECTIONS, make_outline_node
from app.agents.writer import make_writer_node, route_after_writer
from app.llm.base import LLMResponseFormatError
from app.models.state import initial_state


async def test_outline_node_produces_sections() -> None:
    provider = ScriptedProvider([OUTLINE_JSON])
    node = make_outline_node(provider, max_retries=0)

    update = await node(initial_state("写一篇综述", task_id="t-outline"))

    titles = [section["title"] for section in update["outline"]]
    assert titles == [section["title"] for section in OUTLINE_PAYLOAD["sections"]]
    assert all(section["content"] == "" for section in update["outline"])
    assert update["step_results"][0]["step_id"] == "outline"
    assert provider.json_modes == [True]


async def test_outline_node_retries_then_raises_on_bad_json() -> None:
    provider = ScriptedProvider(["坏的", "还是坏的"])
    node = make_outline_node(provider, max_retries=1)

    with pytest.raises(LLMResponseFormatError):
        await node(initial_state("x", task_id="t"))
    assert len(provider.calls) == 2


async def test_writer_writes_one_section_per_invocation() -> None:
    outline_state = initial_state("写一篇综述", task_id="t-writer")
    outline_state["outline"] = [
        {"title": "引言", "content": ""},
        {"title": "方法", "content": ""},
    ]
    provider = ScriptedProvider(["第一章正文"])
    node = make_writer_node(provider)

    first = await node(outline_state)

    assert len(first["sections"]) == 1
    assert first["sections"][0]["title"] == "引言"
    assert first["sections"][0]["content"] == "第一章正文"
    assert first["current_step"] == "chapter_1"
    assert first["step_results"][0]["step_id"] == "chapter_1"

    # 已写 1 章，第二次调用写第 2 章
    outline_state["sections"] = first["sections"]
    second = await node(outline_state)
    assert second["sections"][0]["title"] == "方法"
    assert second["current_step"] == "chapter_2"


async def test_writer_does_nothing_when_outline_finished() -> None:
    state = initial_state("x", task_id="t")
    state["outline"] = [{"title": "唯一章节", "content": ""}]
    state["sections"] = [{"title": "唯一章节", "content": DRAFT_TEXT}]

    node = make_writer_node(ScriptedProvider())
    assert await node(state) == {}


def test_route_after_writer_loops_until_done() -> None:
    outline = [
        {"title": "a", "content": ""},
        {"title": "b", "content": ""},
    ]
    assert route_after_writer({"outline": outline, "sections": []}) == "writer"
    assert (
        route_after_writer({"outline": outline, "sections": [{"title": "a", "content": "x"}]})
        == "writer"
    )
    assert (
        route_after_writer(
            {
                "outline": outline,
                "sections": [
                    {"title": "a", "content": "x"},
                    {"title": "b", "content": "y"},
                ],
            }
        )
        == "summarize"
    )


def test_route_after_writer_respects_max_sections_guard() -> None:
    """即使大纲异常膨胀，也不允许无限循环（§27）。"""
    outline = [{"title": f"s{i}", "content": ""} for i in range(MAX_SECTIONS + 5)]
    sections = [{"title": f"s{i}", "content": "x"} for i in range(MAX_SECTIONS)]

    assert route_after_writer({"outline": outline, "sections": sections}) == "summarize"


def test_route_after_writer_without_outline_summarizes() -> None:
    assert route_after_writer({}) == "summarize"
