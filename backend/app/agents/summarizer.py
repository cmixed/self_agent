"""Summarizer 节点（最终整合）。

把逐章生成的 ``sections`` 汇总为整篇文档，并附上「参考来源」。
Validator 在汇总之前完成校验（Phase 4B），因此本节点只做整合，不调用 LLM。
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.llm.base import ChatMessage
from app.models.state import AgentState, StepResult
from app.rag.tools import render_references

logger = get_logger(__name__)


def assemble_document(state: AgentState) -> str:
    """把章节汇总为整篇文档（含标题与「参考来源」）。"""
    plan = state.get("plan")
    goal = (plan or {}).get("goal") or state.get("user_query", "")
    sections = state.get("sections") or []

    parts: list[str] = []
    if goal:
        parts.append(f"# {goal}")
    for section in sections:
        content = section.get("content", "").strip()
        parts.append(f"## {section.get('title', '')}\n\n{content}")

    body = "\n\n".join(part for part in parts if part.strip()).strip()
    if not body:
        # 无章节（例如未生成大纲）时退回单次草稿
        body = (state.get("draft") or "").strip()

    references = render_references(state.get("retrieved_documents") or [])
    return f"{body}\n\n{references}".strip() if references else body


async def summarizer_node(state: AgentState) -> dict:
    draft = assemble_document(state)

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
        "messages": [ChatMessage(role="assistant", content="[summarizer] 已整合最终结果")],
        "step_results": [StepResult(step_id="summarize", status="ok", summary="已整合最终结果")],
    }
