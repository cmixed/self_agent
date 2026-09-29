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
    chapter_index_from_target,
    chapter_target,
    ensure_aligned,
    next_pending_index,
)
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, Section, StepResult
from app.rag.tools import format_context

logger = get_logger(__name__)

_WRITER_SYSTEM_PROMPT = """你是一个中文写作助手。请撰写指定章节的正文。

要求：
1. 只输出该章节的正文，不要重复章节标题，也不要输出「参考来源」列表。
2. 章节内部的小标题必须使用 ### 或更深层级（###/####）；严禁使用 # 或 ##，
   因为章节标题由系统以 ## 层级统一生成。
3. 如果提供了「检索到的资料」，请优先依据资料作答，并用 [编号] 标注引用，
   例如：RAG 通过向量检索增强能力[1]。
4. 如果未提供资料，请只依据通用知识作答，并说明未引用用户资料。
"""


def _render_section_input(
    state: AgentState,
    *,
    title: str,
    index: int,
    total: int,
    rewrite: bool,
) -> str:
    plan = state.get("plan")
    lines = [f"用户任务：{state.get('user_query', '')}"]
    if plan:
        lines.append(f"任务目标：{plan.get('goal', '')}")
    lines.append(f"当前章节（第 {index}/{total} 章）：{title}")

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

    preferences = state.get("user_preferences") or {}
    if preferences:
        rendered = "；".join(f"{key}={value}" for key, value in preferences.items())
        lines.append(f"用户偏好：{rendered}")
    return "\n".join(lines)


def resolve_target_index(state: AgentState, *, max_retries: int) -> tuple[int | None, bool]:
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

    return next_pending_index(state, max_retries=max_retries), False


def make_writer_node(
    llm: LLMProvider, *, max_retries: int = 2
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造 writer 节点（每次撰写或重写一章）。"""

    async def writer_node(state: AgentState) -> dict:
        outline = state.get("outline") or []
        sections = ensure_aligned(list(state.get("sections") or []), outline)

        index, rewrite = resolve_target_index(state, max_retries=max_retries)
        if index is None:
            # 没有需要撰写的内容（正常情况下路由不会再调用本节点）
            return {}

        title = outline[index].get("title", "")
        chapter = index + 1
        total = len(outline)

        messages = [
            ChatMessage(role="system", content=_WRITER_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=_render_section_input(
                    state, title=title, index=chapter, total=total, rewrite=rewrite
                ),
            ),
        ]
        response = await llm.chat(messages, temperature=0.7)

        while len(sections) <= index:
            sections.append(Section(title="", content=""))
        sections[index] = Section(title=title, content=response.content.strip())

        verb = "重写" if rewrite else "撰写"
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
            "messages": [
                ChatMessage(role="assistant", content=f"[writer] 已{verb}第 {chapter} 章：{title}")
            ],
            "step_results": [
                StepResult(
                    step_id=f"chapter_{chapter}",
                    status="ok",
                    summary=f"已{verb}：{title}",
                )
            ],
        }

    return writer_node
