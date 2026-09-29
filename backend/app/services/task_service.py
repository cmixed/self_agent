"""任务服务。

负责组装初始状态、调用 Agent Graph、整理结果。API 层不直接接触 Graph。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from app.api.errors import resolve_llm_error
from app.core.agent_graph import build_graph
from app.core.logging import get_logger
from app.llm.base import LLMError, LLMProvider
from app.models.state import AgentState, initial_state

logger = get_logger(__name__)

# 节点 -> (进行中提示, 完成提示)。仅这些节点会推送给前端（§19）。
_NODE_EVENTS: dict[str, tuple[str, str]] = {
    "planner": ("正在分析任务并生成计划", "已完成任务规划"),
    "writer": ("正在撰写内容", "内容已生成"),
    "summarizer": ("正在整合最终结果", "已整合最终结果"),
}


def task_result(state: AgentState) -> dict[str, Any]:
    """把最终状态整理为 API 结果结构（TaskResponse 的字段集合）。"""
    return {
        "task_id": state.get("task_id", ""),
        "status": state.get("task_status", "failed"),
        "plan": state.get("plan"),
        "step_results": state.get("step_results", []),
        "final_answer": state.get("final_answer", ""),
    }


class TaskService:
    """运行一次 Agent 任务。"""

    def __init__(self, llm: LLMProvider, *, max_retries: int = 2) -> None:
        self._graph = build_graph(llm, max_retries=max_retries)

    async def run(
        self,
        query: str,
        *,
        user_preferences: dict[str, str] | None = None,
        task_id: str | None = None,
    ) -> AgentState:
        run_id = task_id or str(uuid4())
        state = initial_state(query, task_id=run_id, user_preferences=user_preferences)

        logger.info(
            "任务开始",
            extra={"task_id": run_id, "event": "task_started", "status": "running"},
        )
        final_state = await self._graph.ainvoke(state)
        logger.info(
            "任务结束",
            extra={
                "task_id": run_id,
                "event": "task_finished",
                "status": final_state.get("task_status", "unknown"),
            },
        )
        return final_state

    async def stream(
        self,
        query: str,
        *,
        user_preferences: dict[str, str] | None = None,
        task_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """按 §19 协议逐条产出进度事件。

        错误不向外抛出，而是转换为 ``task_failed`` 事件，保证 SSE 连接
        能正常结束并给出可读信息。
        """
        run_id = task_id or str(uuid4())
        state = initial_state(query, task_id=run_id, user_preferences=user_preferences)

        yield _event(run_id, "task_started", status="running", message="任务已创建")
        final_state: AgentState = state

        try:
            async for event in self._graph.astream_events(state, version="v2"):
                name = event.get("name")
                kind = event.get("event")

                if name == "LangGraph" and kind == "on_chain_end":
                    output = (event.get("data") or {}).get("output")
                    if isinstance(output, dict):
                        final_state = output
                    continue

                if name not in _NODE_EVENTS:
                    continue

                start_message, done_message = _NODE_EVENTS[name]
                if kind == "on_chain_start":
                    yield _event(run_id, f"{name}_started", status="running", message=start_message)
                elif kind == "on_chain_end":
                    payload: dict[str, Any] = {
                        "step": name,
                        "status": "ok",
                        "message": done_message,
                    }
                    output = (event.get("data") or {}).get("output")
                    if name == "planner" and isinstance(output, dict):
                        payload["plan"] = output.get("plan")
                    yield _event(run_id, f"{name}_completed", **payload)
        except LLMError as exc:
            _, detail = resolve_llm_error(exc)
            logger.warning(
                "任务失败",
                extra={
                    "task_id": run_id,
                    "event": "task_failed",
                    "status": "error",
                    "error_type": exc.error_type,
                },
            )
            yield _event(
                run_id,
                "task_failed",
                status="error",
                message=detail,
                error_type=exc.error_type,
            )
            return

        status = final_state.get("task_status", "failed")
        if status != "completed":
            yield _event(run_id, "task_failed", status="error", message="任务未能正常完成")
            return

        logger.info(
            "任务结束",
            extra={"task_id": run_id, "event": "task_completed", "status": "completed"},
        )
        yield _event(
            run_id,
            "task_completed",
            status="completed",
            message="任务完成",
            result=task_result(final_state),
        )


def _event(
    task_id: str,
    event: str,
    *,
    status: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    """构造一条 §19 事件。"""
    payload: dict[str, Any] = {
        "task_id": task_id,
        "event": event,
        "step": extra.pop("step", None),
        "status": status,
        "message": message,
    }
    payload.update(extra)
    return payload
