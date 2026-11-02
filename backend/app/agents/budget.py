"""资料量自适应的写作预算。

长文篇幅不能只用「用户目标 / 章节数」硬分摊：知识库只有一两千字时，模型为了
达到固定目标很容易注水。这里把预算拆成四个概念（见 ``WritingBudget``）：

- ``requested_chars``：用户/配置请求的目标；
- ``source_chars``：Writer 实际能看到的检索资料字数；
- ``effective_chars``：资料与请求共同支撑的参考篇幅；
- ``source_limited``：是否因资料不足而下调。

预算是**纯函数**，不调用 LLM，也不直接改 state；outline 负责计算并持久化，
其余节点读取同一份结果。
"""

from __future__ import annotations

from typing import cast

from app.core.coerce import as_int
from app.core.limits import (
    CHAPTER_LENGTH_HIGH_FACTOR,
    CHAPTER_LENGTH_LOW_FACTOR,
    DEFAULT_MAX_SECTIONS,
    DEFAULT_TARGET_SECTIONS,
    DEFAULT_TOTAL_CHARS,
    LONGFORM_SECTION_BUDGET_CHARS,
    MIN_GROUNDED_TOTAL_CHARS,
    MIN_SECTIONS,
    SOURCE_EXPANSION_FACTOR,
    SOURCE_LIMITED_RATIO,
)
from app.models.state import AgentState, WritingBudget
from app.rag.tools import dedupe_documents, source_char_count


def requested_chars_for_state(state: AgentState, *, fallback: int = DEFAULT_TOTAL_CHARS) -> int:
    """读取用户/配置请求目标；旧 state 没有 profile 时使用节点配置。"""
    profile = state.get("task_profile") or {}
    value = as_int(profile.get("target_chars"), 0)
    return max(1, value or int(fallback))


def needs_retrieval(state: AgentState) -> bool:
    """本次任务是否声明需要知识库检索。

    优先使用 Planner 的计划（真正决定是否执行 researcher），旧 state 没有
    plan 时退回 task_profile 的路由判断。
    """
    if state.get("retrieval_mode") == "none":
        return False
    plan = state.get("plan")
    if isinstance(plan, dict) and "needs_retrieval" in plan:
        return bool(plan.get("needs_retrieval"))
    profile = state.get("task_profile") or {}
    return bool(profile.get("needs_retrieval"))


def compute_writing_budget(
    state: AgentState,
    *,
    fallback_requested_chars: int = DEFAULT_TOTAL_CHARS,
    target_sections: int = DEFAULT_TARGET_SECTIONS,
    max_sections: int = DEFAULT_MAX_SECTIONS,
) -> WritingBudget:
    """按当前检索结果计算写作预算。

    ``source_chars`` 使用 Writer 实际可见的字数（去重、按每条资料上限截断），
    而不是原始 chunk 长度，避免高估资料能力。
    """
    requested = requested_chars_for_state(state, fallback=fallback_requested_chars)
    documents = dedupe_documents(state.get("retrieved_documents") or [])
    source_chars = source_char_count(documents)
    source_count = len(documents)
    retrieval_required = needs_retrieval(state)

    source_limited = retrieval_required and source_chars < int(requested * SOURCE_LIMITED_RATIO)
    no_sources = retrieval_required and source_count == 0

    if source_limited:
        effective = min(
            requested,
            max(MIN_GROUNDED_TOTAL_CHARS, int(source_chars * SOURCE_EXPANSION_FACTOR)),
        )
    else:
        effective = requested

    section_cap = max(MIN_SECTIONS, min(target_sections, max_sections))
    recommended = max(
        MIN_SECTIONS,
        min(
            section_cap,
            (max(1, effective) + LONGFORM_SECTION_BUDGET_CHARS - 1)
            // LONGFORM_SECTION_BUDGET_CHARS,
        ),
    )

    if not retrieval_required:
        reason = f"无需检索，按请求目标 {requested} 字"
    elif no_sources:
        reason = f"需要检索但未获得资料，参考篇幅收束为 {effective} 字"
    elif source_limited:
        reason = (
            f"检索资料约 {source_chars} 字，低于请求目标 {requested} 字，"
            f"参考篇幅调整为 {effective} 字"
        )
    else:
        reason = f"检索资料约 {source_chars} 字，按请求目标 {requested} 字"

    return WritingBudget(
        requested_chars=requested,
        source_chars=source_chars,
        source_count=source_count,
        effective_chars=effective,
        source_limited=source_limited,
        no_sources=no_sources,
        recommended_sections=recommended,
        reason=reason,
    )


def resolve_writing_budget(
    state: AgentState,
    *,
    fallback_requested_chars: int = DEFAULT_TOTAL_CHARS,
    target_sections: int = DEFAULT_TARGET_SECTIONS,
    max_sections: int = DEFAULT_MAX_SECTIONS,
) -> WritingBudget:
    """读取已持久化预算；旧 checkpoint 缺失时按当前 state 重算。"""
    budget = state.get("writing_budget")
    if isinstance(budget, dict) and int(budget.get("effective_chars") or 0) > 0:
        return cast(WritingBudget, budget)
    return compute_writing_budget(
        state,
        fallback_requested_chars=fallback_requested_chars,
        target_sections=target_sections,
        max_sections=max_sections,
    )


def chapter_char_target(effective_chars: int, total_sections: int) -> tuple[int, int]:
    """把有效篇幅分摊为单章参考区间 (下限, 上限)。

    这是**软参考**：资料不足时模型可以写得更短；不设置 max_tokens 硬截断。
    """
    per_chapter = max(200, int(effective_chars / max(1, total_sections)))
    low = max(200, int(per_chapter * CHAPTER_LENGTH_LOW_FACTOR))
    high = max(low + 100, int(per_chapter * CHAPTER_LENGTH_HIGH_FACTOR))
    return low, high


def budget_context(budget: WritingBudget) -> str:
    """渲染给提示词的统一预算说明。"""
    if budget["source_count"] == 0 and not budget["source_limited"]:
        text = (
            f"写作预算：用户请求 {budget['requested_chars']} 字；"
            f"本次参考篇幅 {budget['effective_chars']} 字（无需检索）。"
        )
    else:
        text = (
            f"写作预算：用户请求 {budget['requested_chars']} 字；"
            f"检索资料约 {budget['source_chars']} 字（{budget['source_count']} 条）；"
            f"本次参考篇幅 {budget['effective_chars']} 字。"
        )
    if budget["no_sources"]:
        text += (
            " 未检索到用户资料：不要写成完整长文，不要编造引用；用简短篇幅说明无法基于资料展开。"
        )
    elif budget["source_limited"]:
        text += (
            " 资料量不足以支撑请求篇幅：宁可写短，不要用重复、套话或"
            "通用知识硬凑；资料未覆盖的内容不要展开。"
        )
    return text
