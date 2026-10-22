"""Writer 节点：逐章撰写正文。

Phase 4B / 4C：

- 每次调用只写一章，由 Graph 循环驱动（§15）；
- ``sections`` 与 ``outline`` 下标对齐并采用覆盖语义，因此既能填充新章、
  也能在 Validator 判定 ``retry_writer`` 时**重写**指定章节；
- 已达重试上限的章节会被跳过，**不影响其他章节继续执行**。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.agents.chapters import (
    MAX_SECTIONS,
    chapter_index_from_target,
    chapter_target,
    ensure_aligned,
    next_pending_index,
)
from app.agents.preferences import render_preferences
from app.agents.skills import render_skill_outputs
from app.core.limits import DEFAULT_TOTAL_CHARS
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, Section, StepResult
from app.prompts import render_prompt
from app.rag.tools import format_context

logger = get_logger(__name__)

_WRITER_SYSTEM_PROMPT = render_prompt("writer.md")


def chapter_char_target(total_chars: int, total_sections: int) -> tuple[int, int]:
    """按章节数把目标总字数分摊为单章区间 (下限, 上限)。

    软目标：写进提示词让模型自我调节，**不做 max_tokens 硬截断**——
    硬截断只会得到半截章节。单章下限兜底 200 字，避免章节过多时目标失去意义。
    """
    per_chapter = max(200, int(total_chars / max(1, total_sections)))
    return int(per_chapter * 0.8), int(per_chapter * 1.3)


def _render_section_input(
    state: AgentState,
    *,
    title: str,
    index: int,
    total: int,
    rewrite: bool,
    char_target: tuple[int, int] | None = None,
) -> str:
    plan = state.get("plan")
    lines = [f"用户任务：{state.get('user_query', '')}"]
    if plan:
        lines.append(f"任务目标：{plan.get('goal', '')}")
    lines.append(f"当前章节（第 {index}/{total} 章）：{title}")
    if char_target is not None:
        low, high = char_target
        lines.append(f"本章目标篇幅：约 {low}-{high} 字（可接受 ±30%，不要为凑字数而注水）")

    if rewrite:
        validations = state.get("chapter_validations") or {}
        result = validations.get(chapter_target(index - 1)) or {}
        issues = result.get("issues") or []
        if issues:
            rendered = "\n".join(f"- {issue}" for issue in issues)
            lines.append(f"上一轮校验发现的问题（请针对性修正）：\n{rendered}")

    documents = state.get("retrieved_documents") or []
    if documents:
        lines.append(f"检索到的资料（请用 [编号] 引用）：\n{format_context(documents)}")
    elif plan and plan.get("needs_retrieval"):
        lines.append(
            "注意：本任务需要检索用户资料，但知识库中没有检索到相关内容。"
            "请只依据通用知识作答，并明确说明未引用用户资料。"
        )

    skill_context = render_skill_outputs(state)
    if skill_context:
        lines.append(
            "已完成的技能分析结论（可作为写作依据，但其中若出现 [编号]，"
            "一律以「检索到的资料」的编号为准，不得引用资料之外的编号）：\n"
            f"{skill_context}"
        )

    rendered = render_preferences(state)
    if rendered:
        lines.append(rendered)
    return "\n".join(lines)


def resolve_target_index(
    state: AgentState, *, max_retries: int, max_sections: int = MAX_SECTIONS
) -> tuple[int | None, bool]:
    """决定本次要写哪一章。

    返回 ``(章节下标, 是否重写)``；``None`` 表示没有需要撰写的内容。
    """
    outline = state.get("outline") or []
    sections = state.get("sections") or []
    retry_counts = state.get("retry_counts") or {}
    validation = state.get("validation_result")

    if (
        isinstance(validation, dict)
        and not validation.get("passed")
        and validation.get("suggested_action") == "retry_writer"
    ):
        index = chapter_index_from_target(str(validation.get("target", "")))
        if index is not None and index < len(outline) and index < len(sections):
            target = chapter_target(index)
            has_content = bool((sections[index].get("content") or "").strip())
            # 仅在该章确实写过、且仍有重试预算时才重写；否则跳过它继续其他章节
            if has_content and retry_counts.get(target, 0) < max_retries:
                return index, True

    return next_pending_index(state, max_retries=max_retries, max_sections=max_sections), False


def make_writer_node(
    llm: LLMProvider,
    *,
    max_retries: int = 2,
    max_sections: int = MAX_SECTIONS,
    target_total_chars: int = DEFAULT_TOTAL_CHARS,
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造 writer 节点（每次撰写或重写一章）。

    篇幅用「目标字数」软约束；输出被长度上限截断时（``finish_reason=length``）
    追加**一次**有限续写，仍然截断则把事实写进 step_result 与消息（可见、不静默）。
    """

    async def writer_node(state: AgentState) -> dict:
        outline = state.get("outline") or []
        sections = ensure_aligned(list(state.get("sections") or []), outline)

        index, rewrite = resolve_target_index(
            state, max_retries=max_retries, max_sections=max_sections
        )
        if index is None:
            # 没有需要撰写的内容（正常情况下路由不会再调用本节点）
            return {}

        title = outline[index].get("title", "")
        chapter = index + 1
        total = len(outline)

        char_target = chapter_char_target(target_total_chars, total)
        messages = [
            ChatMessage(role="system", content=_WRITER_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=_render_section_input(
                    state,
                    title=title,
                    index=chapter,
                    total=total,
                    rewrite=rewrite,
                    char_target=char_target,
                ),
            ),
        ]
        response = await llm.chat(messages, temperature=0.7)
        content = response.content.strip()
        truncated = response.finish_reason == "length"

        # 被输出长度上限截断：追加一次有限续写（有上限，绝不无限续）
        if truncated and content:
            tail = content[-500:]
            continuation = await llm.chat(
                [
                    ChatMessage(role="system", content=_WRITER_SYSTEM_PROMPT),
                    ChatMessage(
                        role="user",
                        content=render_prompt(
                            "writer_continue.md",
                            title=title,
                            tail=tail,
                        ),
                    ),
                ],
                temperature=0.7,
            )
            if continuation.content.strip():
                content = f"{content}\n{continuation.content.strip()}"
            truncated = continuation.finish_reason == "length"
            logger.warning(
                "章节输出被长度上限截断，已尝试一次续写",
                extra={
                    "task_id": state.get("task_id"),
                    "node": "writer",
                    "event": "chapter_truncated",
                    "status": "warning",
                    "chapter": chapter,
                    "still_truncated": truncated,
                },
            )

        while len(sections) <= index:
            sections.append(Section(title="", content=""))
        sections[index] = Section(title=title, content=content)

        verb = "重写" if rewrite else "撰写"
        summary = f"已{verb}：{title}"
        if truncated:
            summary += "（本章因输出长度上限被截断，内容可能不完整）"
        logger.info(
            "writer 完成章节",
            extra={
                "task_id": state.get("task_id"),
                "node": "writer",
                "event": "writer_completed",
                "status": "ok",
            },
        )
        return {
            "sections": sections,
            "current_step": f"chapter_{chapter}",
            "task_status": "writing",
            "messages": [ChatMessage(role="assistant", content=f"[writer] {summary}")],
            "step_results": [
                StepResult(
                    step_id=f"chapter_{chapter}",
                    status="ok" if not truncated else "error",
                    summary=summary,
                )
            ],
        }

    return writer_node
