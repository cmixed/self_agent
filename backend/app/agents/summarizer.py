"""Summarizer 节点（最终整合）。

把各章节汇总为整篇文档，统一追加「参考来源」，并**明确标记未通过校验的章节**。
Validator 在汇总之前完成校验（Phase 4B），因此本节点不调用 LLM。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.agents.chapters import chapter_target, failed_chapters
from app.core.logging import get_logger
from app.llm.base import ChatMessage
from app.models.state import AgentState, StepResult
from app.rag.tools import render_references

logger = get_logger(__name__)


def assemble_document(state: AgentState, *, max_retries: int = 2) -> str:
    """把章节汇总为整篇文档（含标题、「参考来源」与失败章节标记）。"""
    plan = state.get("plan")
    goal = (plan or {}).get("goal") or state.get("user_query", "")
    outline = state.get("outline") or []
    sections = state.get("sections") or []
    validations = state.get("chapter_validations") or {}
    failed = set(failed_chapters(state, max_retries=max_retries))

    parts: list[str] = []
    if goal:
        parts.append(f"# {goal}")

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


def make_summarizer_node(*, max_retries: int = 2) -> Callable[[AgentState], Awaitable[dict]]:
    """构造 summarizer 节点。"""

    async def summarizer_node(state: AgentState) -> dict:
        draft = assemble_document(state, max_retries=max_retries)
        failed = failed_chapters(state, max_retries=max_retries)
        summary = "已整合最终结果"
        if failed:
            summary += f"（{len(failed)} 个章节未通过校验）"

        logger.info(
            "summarizer 完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "summarizer",
                "event": "task_completed",
                "status": "ok",
            },
        )
        return {
            "draft": draft,
            "final_answer": draft,
            "current_step": "summarize",
            "task_status": "completed",
            "is_complete": True,
            "messages": [ChatMessage(role="assistant", content=f"[summarizer] {summary}")],
            "step_results": [StepResult(step_id="summarize", status="ok", summary=summary)],
        }

    return summarizer_node
