"""Summarizer 节点（最终整合）。

把各章节汇总为整篇文档，统一追加「参考来源」，并**明确标记未通过校验的章节**。
Validator 在汇总之前完成校验（Phase 4B），因此本节点不调用 LLM。
"""

from __future__ import annotations

import re

from app.agents.base import AgentNode
from app.agents.budget import resolve_writing_budget
from app.agents.chapters import MAX_SECTIONS, chapter_target, failed_chapters
from app.core.limits import (
    DEFAULT_TOTAL_CHARS,
    LONGFORM_LENGTH_HIGH_FACTOR,
    LONGFORM_LENGTH_LOW_FACTOR,
)
from app.core.logging import get_logger
from app.llm.base import ChatMessage
from app.models.state import AgentState, StepResult, WritingBudget
from app.rag.tools import render_references
from app.services.verbatim_service import (
    VerbatimOutput,
    render_verbatim_appendix,
)

logger = get_logger(__name__)

_VERBATIM_PLACEHOLDER_RE = re.compile(r"\[\[VERBATIM:(\d+)\]\]")
_REFERENCES_MARKER = "\n\n## 参考来源"


def _body_chars(document: str) -> int:
    """统计正文有效字符（不含空白与「参考来源」列表）。"""
    body = document.split("\n\n## 参考来源", 1)[0]
    return sum(1 for char in body if not char.isspace())


def audit_length(
    document: str,
    target_total_chars: int,
    *,
    source_limited: bool = False,
    requested_chars: int | None = None,
) -> str | None:
    """最终篇幅审计：只报告偏离，不自动改写正文。

    自动截断会破坏章节结构，自动扩写则会注水；因此这里只把事实写进
    步骤摘要与日志，让用户/前端能看到「实际多少字、目标多少字」。
    ``source_limited`` 时低于参考目标不算异常，只说明已按资料量收束。
    """
    actual = _body_chars(document)
    low = int(target_total_chars * LONGFORM_LENGTH_LOW_FACTOR)
    high = int(target_total_chars * LONGFORM_LENGTH_HIGH_FACTOR)
    if actual > high:
        ratio = actual / max(1, target_total_chars)
        return f"正文约 {actual} 字，明显超出目标 {target_total_chars} 字（{ratio:.1f} 倍）"
    if actual < low:
        if source_limited:
            requested = requested_chars or target_total_chars
            return (
                f"正文约 {actual} 字，已按资料可支撑范围收束"
                f"（参考 {target_total_chars} 字，请求 {requested} 字）"
            )
        return f"正文约 {actual} 字，明显少于目标 {target_total_chars} 字"
    return None


def limitation_note(budget: WritingBudget) -> str:
    """资料不足时在最终文档末尾给出明确缺口，而不是让每章重复说明。"""
    if budget["no_sources"]:
        return (
            "## 资料限制说明\n\n"
            "本次未检索到与任务相关的用户资料，正文未引用用户资料；"
            "如需基于资料的长文，请补充文档后重新生成。"
        )
    if budget["source_limited"]:
        return (
            "## 资料限制说明\n\n"
            f"本次检索到的用户资料约 {budget['source_chars']} 字，"
            f"系统将参考篇幅调整为约 {budget['effective_chars']} 字"
            f"（原请求 {budget['requested_chars']} 字）。"
            "资料未覆盖的内容未作展开，建议补充资料后重新生成。"
        )
    return ""


def append_limitation_note(document: str, budget: WritingBudget) -> str:
    """把资料限制说明放在「参考来源」之前；没有缺口时原样返回。"""
    note = limitation_note(budget)
    if not note:
        return document
    marker = "\n\n## 参考来源"
    if marker in document:
        head, tail = document.split(marker, 1)
        return f"{head}\n\n{note}{marker}{tail}"
    return f"{document}\n\n{note}"


def _verbatim_blocks(outputs: list[VerbatimOutput]) -> list[str]:
    return [render_verbatim_appendix(output) for output in outputs]


def inject_verbatim(document: str, state: AgentState) -> str:
    """把系统原文注入最终文档。

    必须在 **篇幅审计与资料限制说明之后** 调用：

    - 原文里的 ``[1]`` 不参与系统引用编号检查；
    - 原文里的 ``## 参考来源`` 不会干扰资料限制说明的拆分；
    - 原文不计入模型生成的篇幅统计。

    有占位符 → 原地替换；没有占位符但计划确实准备了原文 → 在参考来源之前追加。
    """
    outputs = list(state.get("verbatim_outputs") or [])
    if not outputs:
        return document

    blocks = _verbatim_blocks(outputs)
    by_index = {str(index): block for index, block in enumerate(blocks, start=1)}
    used = False

    def replace(match: re.Match[str]) -> str:
        nonlocal used
        block = by_index.get(match.group(1))
        if block is None:
            logger.warning(
                "原文占位符编号非法，已移除",
                extra={"node": "summarizer", "event": "verbatim_placeholder_invalid"},
            )
            return ""
        used = True
        return block

    injected = _VERBATIM_PLACEHOLDER_RE.sub(replace, document)
    if used:
        return injected

    appendix = "\n\n".join(blocks)
    if _REFERENCES_MARKER in injected:
        head, tail = injected.split(_REFERENCES_MARKER, 1)
        return f"{head}\n\n{appendix}{_REFERENCES_MARKER}{tail}"
    return f"{injected}\n\n{appendix}".strip()


def assemble_document(
    state: AgentState, *, max_retries: int = 2, max_sections: int = MAX_SECTIONS
) -> str:
    """把章节汇总为整篇文档（含标题、「参考来源」与失败章节标记）。"""
    plan = state.get("plan")
    goal = (plan or {}).get("goal") or state.get("user_query", "")
    outline = state.get("outline") or []
    sections = state.get("sections") or []
    validations = state.get("chapter_validations") or {}
    failed = set(failed_chapters(state, max_retries=max_retries, max_sections=max_sections))

    parts: list[str] = []
    if goal:
        parts.append(f"# {goal}")

    if len(outline) == 1:
        # 单章表示「整篇不划分章节」：只用任务目标做标题，不再额外生成 ## 章节标题。
        index = 0
        content = sections[0].get("content", "").strip() if sections else ""
        if index in failed:
            issues = (validations.get(chapter_target(index)) or {}).get("issues") or []
            reason = "；".join(issues) if issues else "未通过校验"
            content = (
                f"> ⚠️ 内容未通过校验（已达重试上限 {max_retries}）：{reason}\n\n{content}"
            ).strip()
        if not goal:
            title = outline[0].get("title", "")
            parts.append(f"# {title}")
        parts.append(content)
    else:
        for index, section in enumerate(outline):
            title = section.get("title", "")
            content = sections[index].get("content", "").strip() if index < len(sections) else ""
            if index in failed:
                issues = (validations.get(chapter_target(index)) or {}).get("issues") or []
                reason = "；".join(issues) if issues else "未通过校验"
                content = (
                    f"> ⚠️ 本章未通过校验（已达重试上限 {max_retries}）：{reason}\n\n{content}"
                ).strip()
            parts.append(f"## {title}\n\n{content}")

    body = "\n\n".join(part for part in parts if part.strip()).strip()
    if not body:
        # 无章节（例如未生成大纲）时退回单次草稿
        body = (state.get("draft") or "").strip()

    references = render_references(state.get("retrieved_documents") or [])
    return f"{body}\n\n{references}".strip() if references else body


def make_summarizer_node(
    *,
    max_retries: int = 2,
    max_sections: int = MAX_SECTIONS,
    target_total_chars: int = DEFAULT_TOTAL_CHARS,
) -> AgentNode:
    """构造 summarizer 节点。"""

    async def summarizer_node(state: AgentState) -> dict:
        budget = resolve_writing_budget(
            state,
            fallback_requested_chars=target_total_chars,
            max_sections=max_sections,
        )
        draft = assemble_document(state, max_retries=max_retries, max_sections=max_sections)
        failed = failed_chapters(state, max_retries=max_retries, max_sections=max_sections)
        summary = "已整合最终结果"
        if failed:
            summary += f"（{len(failed)} 个章节未通过校验）"
        length_note = audit_length(
            draft,
            budget["effective_chars"],
            source_limited=budget["source_limited"],
            requested_chars=budget["requested_chars"],
        )
        if length_note:
            summary += f"；{length_note}"
        if budget["source_limited"] or budget["no_sources"]:
            summary += f"；{budget['reason']}"
        # 顺序很重要：先审计/说明，再注入原文，避免原文的长度与引用编号干扰系统判断。
        draft = append_limitation_note(draft, budget)
        draft = inject_verbatim(draft, state)
        verbatim_outputs = list(state.get("verbatim_outputs") or [])
        if verbatim_outputs:
            first = verbatim_outputs[0]
            summary += (
                f"；已直接输出《{first.get('filename', '')}》原文（约 {first.get('chars', 0)} 字）"
            )

        logger.info(
            "summarizer 完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "summarizer",
                "event": "task_completed",
                "status": "ok",
                "requested_chars": budget["requested_chars"],
                "target_chars": budget["effective_chars"],
                "source_chars": budget["source_chars"],
                "source_limited": budget["source_limited"],
                "actual_chars": _body_chars(draft),
                "length_warning": length_note,
            },
        )
        return {
            "writing_budget": budget,
            "draft": draft,
            "final_answer": draft,
            "current_step": "summarize",
            "task_status": "completed",
            "is_complete": True,
            "messages": [ChatMessage(role="assistant", content=f"[summarizer] {summary}")],
            "step_results": [StepResult(step_id="summarize", status="ok", summary=summary)],
        }

    return summarizer_node
