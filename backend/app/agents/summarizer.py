"""Summarizer 节点（最终整合）。

Phase 2 只做整合：把草稿收敛为 final_answer 并标记任务完成，不额外调用 LLM。
长文的章节汇总属于 Phase 4（AGENTS.md §15）。
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.llm.base import ChatMessage
from app.models.state import AgentState, StepResult

logger = get_logger(__name__)


async def summarizer_node(state: AgentState) -> dict:
    final_answer = (state.get("draft") or "").strip()

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
        "final_answer": final_answer,
        "current_step": "summarize",
        "task_status": "completed",
        "is_complete": True,
        "messages": [ChatMessage(role="assistant", content="[summarizer] 已整合最终结果")],
        "step_results": [StepResult(step_id="summarize", status="ok", summary="已整合最终结果")],
    }
