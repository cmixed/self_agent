"""资料量自适应写作预算的回归测试。

重点覆盖：短资料不硬凑、资料充足不降级、旧 state 可重算、最终可见缺口。
"""

from __future__ import annotations

import json

from fakes import OUTLINE_JSON, ScriptedProvider

from app.agents.budget import (
    chapter_char_target,
    compute_writing_budget,
    resolve_writing_budget,
)
from app.agents.outline import make_outline_node
from app.agents.skills import skill_output_target_chars
from app.agents.summarizer import make_summarizer_node
from app.agents.validator import make_validator_node
from app.agents.writer import make_writer_node
from app.models.schemas import TaskResponse
from app.models.state import AgentState, Plan, RetrievedDocument, initial_state
from app.models.task_profile import resolve_profile
from app.rag.tools import source_char_count
from app.services.task_service import task_result


def _doc(content: str, *, chunk_id: str = "c1", filename: str = "a.md") -> RetrievedDocument:
    return {
        "document_id": "d1",
        "filename": filename,
        "page": None,
        "chunk_id": chunk_id,
        "content": content,
        "score": 0.9,
    }


def _state(
    *,
    requested: int = 6000,
    docs: list[RetrievedDocument] | None = None,
    needs_retrieval: bool = True,
    outline: int = 2,
) -> AgentState:
    state = initial_state(
        "根据我的资料写一篇综述",
        task_id="t-budget",
        task_profile={"mode": "longform", "target_chars": requested},
    )
    state["plan"] = Plan(
        goal="写综述",
        needs_retrieval=needs_retrieval,
        steps=[],
    )
    state["retrieved_documents"] = docs or []
    state["outline"] = [
        {"title": f"章节{i + 1}", "content": "", "points": [f"要点{i + 1}"]} for i in range(outline)
    ]
    state["sections"] = [
        {"title": f"章节{i + 1}", "content": "", "points": [f"要点{i + 1}"]} for i in range(outline)
    ]
    return state


def test_no_retrieval_keeps_requested_budget() -> None:
    budget = compute_writing_budget(_state(docs=[], needs_retrieval=False))

    assert budget["requested_chars"] == 6000
    assert budget["source_chars"] == 0
    assert budget["effective_chars"] == 6000
    assert budget["source_limited"] is False
    assert budget["no_sources"] is False
    assert budget["recommended_sections"] == 4


def _docs_1000() -> list[RetrievedDocument]:
    return [
        _doc("甲" * 500, chunk_id="c1"),
        _doc("乙" * 500, chunk_id="c2"),
    ]


def test_short_sources_lower_effective_budget() -> None:
    budget = compute_writing_budget(_state(docs=_docs_1000()))

    assert budget["source_chars"] == 1000
    assert budget["effective_chars"] == 2000
    assert budget["source_limited"] is True
    assert budget["no_sources"] is False
    assert budget["recommended_sections"] == 2


def test_tiny_sources_get_a_short_but_nonzero_budget() -> None:
    budget = compute_writing_budget(_state(docs=[_doc("资料只有两个字")]))

    assert budget["source_chars"] == 7
    assert budget["effective_chars"] == 300
    assert budget["source_limited"] is True
    assert budget["recommended_sections"] == 1


def test_no_sources_is_explicitly_flagged() -> None:
    budget = compute_writing_budget(_state(docs=[]))

    assert budget["source_chars"] == 0
    assert budget["source_count"] == 0
    assert budget["effective_chars"] == 300
    assert budget["source_limited"] is True
    assert budget["no_sources"] is True


def test_sufficient_sources_keep_requested_budget() -> None:
    docs = [_doc(f"{i}" * 1000, chunk_id=f"c{i}") for i in range(5)]
    budget = compute_writing_budget(_state(docs=docs))

    assert budget["source_chars"] == 4000  # 每条可见上限 800
    assert budget["effective_chars"] == 6000
    assert budget["source_limited"] is False


def test_source_char_count_uses_visible_context_limit() -> None:
    assert source_char_count([_doc("甲" * 5000)]) == 800
    assert (
        source_char_count([_doc("甲" * 100, chunk_id="c1"), _doc("乙" * 100, chunk_id="c2")]) == 200
    )


def test_chapter_target_is_a_soft_wider_range() -> None:
    assert chapter_char_target(2000, 2) == (600, 1500)
    assert chapter_char_target(6000, 4) == (900, 2250)
    assert chapter_char_target(300, 1) == (200, 450)


def test_resolve_budget_prefers_persisted_value() -> None:
    state = _state(docs=_docs_1000())
    state["writing_budget"] = {
        "requested_chars": 6000,
        "source_chars": 1000,
        "source_count": 1,
        "effective_chars": 2000,
        "source_limited": True,
        "no_sources": False,
        "recommended_sections": 2,
        "reason": "测试",
    }

    assert resolve_writing_budget(state)["effective_chars"] == 2000


async def test_outline_persists_budget_and_uses_it_in_prompt() -> None:
    provider = ScriptedProvider([OUTLINE_JSON])
    state = _state(docs=_docs_1000())
    node = make_outline_node(provider, max_retries=0)

    update = await node(state)

    assert update["writing_budget"]["effective_chars"] == 2000
    assert update["writing_budget"]["source_limited"] is True
    prompt = provider.calls[0][1].content
    assert "本次参考篇幅 2000 字" in prompt
    assert "资料量不足以支撑请求篇幅" in prompt


async def test_outline_caps_sections_when_sources_are_limited() -> None:
    payload = {"sections": [{"title": f"章节{i + 1}"} for i in range(6)]}
    provider = ScriptedProvider([json.dumps(payload, ensure_ascii=False)])
    state = _state(docs=_docs_1000())
    node = make_outline_node(provider, max_retries=0, max_sections=12)

    update = await node(state)

    # effective 2000 字 → 建议 2 章；资料受限时最多 3 章
    assert len(update["outline"]) == 3
    assert "已按上限 3 截断" in update["step_results"][-1]["summary"]


async def test_writer_uses_effective_budget_and_points() -> None:
    provider = ScriptedProvider(["正文"])
    state = _state(docs=_docs_1000())
    state["plan"] = Plan(goal="写综述", needs_retrieval=True, steps=[])
    node = make_writer_node(provider, max_retries=0, target_total_chars=6000)

    await node(state)

    prompt = provider.calls[0][1].content
    assert "本次参考篇幅 2000 字" in prompt
    assert "本章参考篇幅：约 600-1500 字" in prompt
    assert "本章必须覆盖的要点" in prompt
    assert "要点1" in prompt


async def test_writer_no_sources_asks_for_short_honest_answer() -> None:
    provider = ScriptedProvider(["简短说明"])
    state = _state(docs=[], outline=1)
    node = make_writer_node(provider, max_retries=0)

    await node(state)

    prompt = provider.calls[0][1].content
    assert "未检索到用户资料" in prompt
    assert "不要写成完整长文" in prompt


async def test_validator_gets_source_limited_context() -> None:
    provider = ScriptedProvider()
    state = _state(docs=_docs_1000())
    state.get("sections", [])[1]["content"] = "已有正文"
    node = make_validator_node(provider, max_retries=0, target_total_chars=6000)

    await node(state)

    prompt = provider.calls[0][1].content
    assert "资料量不足以支撑请求篇幅" in prompt
    assert "参考篇幅（本章）：约 600-1500 字" in prompt


async def test_summarizer_adds_limitation_note_before_references() -> None:
    state = _state(docs=[_doc("甲" * 500, chunk_id="c1"), _doc("乙" * 500, chunk_id="c2")])
    state.get("sections", [])[0]["content"] = "第一章正文"
    state.get("sections", [])[1]["content"] = "第二章正文"
    node = make_summarizer_node(max_retries=0, target_total_chars=6000)

    update = await node(state)

    answer = update["final_answer"]
    assert "## 资料限制说明" in answer
    assert "约 1000 字" in answer
    assert answer.index("## 资料限制说明") < answer.index("## 参考来源")


def test_task_result_exposes_budget() -> None:
    state = _state(docs=_docs_1000())
    state["writing_budget"] = compute_writing_budget(state)
    state["final_answer"] = "正文"

    result = task_result(state, max_retries=0)
    parsed = TaskResponse.model_validate(result)

    assert parsed.writing_budget is not None
    assert parsed.writing_budget.effective_chars == 2000
    assert parsed.writing_budget.source_limited is True


def test_skill_target_follows_effective_budget() -> None:
    state = _state(docs=[])
    assert skill_output_target_chars(state) == 300

    state["retrieved_documents"] = [_doc("甲" * 800, chunk_id=f"c{i}") for i in range(4)]
    assert skill_output_target_chars(state) == 2000


def test_explicit_length_overrides_config_target() -> None:
    profile = resolve_profile("写一篇 3000 字综述", target_total_chars=6000)
    assert profile.mode == "longform"
    assert profile.target_chars == 3000

    capped = resolve_profile("写一篇 99999 字综述", target_total_chars=6000)
    assert capped.target_chars == 40000

    short_longform = resolve_profile("写一篇 1000 字综述", target_total_chars=6000)
    assert short_longform.mode == "longform"
    assert short_longform.target_chars == 1000

    brief = resolve_profile("不超过 500 字总结一下这份资料", target_total_chars=6000)
    assert brief.mode == "brief"
    assert brief.target_chars == 500


async def test_outline_points_flow_to_sections() -> None:
    payload = {
        "sections": [
            {"title": "引言", "points": ["背景", "问题定义"]},
            {"title": "方法", "points": ["检索", "生成"]},
        ]
    }
    provider = ScriptedProvider([json.dumps(payload, ensure_ascii=False)])
    node = make_outline_node(provider, max_retries=0)

    update = await node(initial_state("写综述", task_id="t-points"))

    assert update["outline"][0]["points"] == ["背景", "问题定义"]
    assert update["sections"][1]["points"] == ["检索", "生成"]


async def test_outline_tolerates_points_as_text() -> None:
    payload = {"sections": [{"title": "引言", "points": "背景\n问题定义"}]}
    provider = ScriptedProvider([json.dumps(payload, ensure_ascii=False)])
    node = make_outline_node(provider, max_retries=0)

    update = await node(initial_state("写综述", task_id="t-points-string"))

    assert update["outline"][0]["points"] == ["背景", "问题定义"]
