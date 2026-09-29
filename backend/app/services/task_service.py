"""任务服务。

负责组装初始状态、调用 Agent Graph、整理结果。API 层不直接接触 Graph。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import uuid4

from app.core.agent_graph import build_graph
from app.core.errors import resolve_error
from app.core.logging import get_logger
from app.llm.base import LLMError, LLMProvider
from app.models.state import AgentState, RetrievedDocument, initial_state
from app.rag.tools import RagTool

logger = get_logger(__name__)

# 节点 -> (进行中提示, 完成提示)。仅这些节点会推送给前端（§19）。
_NODE_EVENTS: dict[str, tuple[str, str]] = {
    "planner": ("正在分析任务并生成计划", "已完成任务规划"),
    "researcher": ("正在检索个人知识库", "知识库检索完成"),
    "outline": ("正在生成文章大纲", "大纲已生成"),
    "writer": ("正在撰写内容", "章节已完成"),
    "summarizer": ("正在整合最终结果", "已整合最终结果"),
}


def _sources(documents: list[RetrievedDocument]) -> list[dict[str, Any]]:
    """把检索结果整理为去重的来源列表，编号与正文引用 [n] 对应。"""
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    for index, document in enumerate(documents, start=1):
        chunk_id = document.get("chunk_id", "")
        if chunk_id and chunk_id in seen:
            continue
        seen.add(chunk_id)
        sources.append(
            {
                "index": index,
                "document_id": document.get("document_id", ""),
                "filename": document.get("filename", ""),
                "page": document.get("page"),
                "chunk_id": chunk_id,
                "score": document.get("score"),
            }
        )
    return sources


def task_result(state: AgentState) -> dict[str, Any]:
    """把最终状态整理为 API 结果结构（TaskResponse 的字段集合）。"""
    return {
        "task_id": state.get("task_id", ""),
        "status": state.get("task_status", "failed"),
        "plan": state.get("plan"),
        "outline": [section.get("title", "") for section in (state.get("outline") or [])],
        "step_results": state.get("step_results", []),
        "sources": _sources(state.get("retrieved_documents") or []),
        "final_answer": state.get("final_answer", ""),
    }


def _chapter_index(node_input: Any) -> int | None:
    """从节点输入推断当前要撰写第几章（已写章节数 + 1）。"""
    if not isinstance(node_input, dict):
        return None
    sections = node_input.get("sections")
    written = len(sections) if isinstance(sections, list) else 0
    return written + 1


class TaskService:
    """运行一次 Agent 任务。"""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        rag_tool_provider: Callable[[], RagTool] | None = None,
        max_retries: int = 2,
    ) -> None:
        self._graph = build_graph(llm, rag_tool_provider=rag_tool_provider, max_retries=max_retries)

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
                    extra: dict[str, Any] = {}
                    message = start_message
                    if name == "writer":
                        chapter = _chapter_index((event.get("data") or {}).get("input"))
                        if chapter is not None:
                            message = f"正在撰写第 {chapter} 章"
                            extra["step"] = f"chapter_{chapter}"
                    yield _event(
                        run_id, f"{name}_started", status="running", message=message, **extra
                    )
                elif kind == "on_chain_end":
                    payload: dict[str, Any] = {
                        "step": name,
                        "status": "ok",
                        "message": done_message,
                    }
                    output = (event.get("data") or {}).get("output")
                    if isinstance(output, dict):
                        if name == "planner":
                            payload["plan"] = output.get("plan")
                        if name == "researcher":
                            payload["retrieved_count"] = len(
                                output.get("retrieved_documents") or []
                            )
                        if name == "outline":
                            payload["outline"] = [
                                section.get("title", "")
                                for section in (output.get("outline") or [])
                            ]
                        if name == "writer":
                            payload["step"] = output.get("current_step") or name
                    yield _event(run_id, f"{name}_completed", **payload)
        except LLMError as exc:
            _, detail = resolve_error(exc)
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
