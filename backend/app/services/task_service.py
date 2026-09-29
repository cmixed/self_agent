"""任务服务。

负责组装初始状态、调用 Agent Graph、整理结果。API 层不直接接触 Graph。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import uuid4

from langgraph.errors import GraphRecursionError

from app.agents.chapters import chapter_index_from_target, chapter_target, failed_chapters
from app.core.agent_graph import build_graph, recursion_limit
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
    "validator": ("正在校验内容质量", "内容校验完成"),
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


def task_result(state: AgentState, *, max_retries: int) -> dict[str, Any]:
    """把最终状态整理为 API 结果结构（TaskResponse 的字段集合）。"""
    failed = failed_chapters(state, max_retries=max_retries)
    return {
        "task_id": state.get("task_id", ""),
        "status": state.get("task_status", "failed"),
        "plan": state.get("plan"),
        "outline": [section.get("title", "") for section in (state.get("outline") or [])],
        "step_results": state.get("step_results", []),
        "sources": _sources(state.get("retrieved_documents") or []),
        "validation": state.get("validation_result"),
        "retry_count": state.get("retry_count", 0),
        "failed_chapters": [chapter_target(index) for index in failed],
        "final_answer": state.get("final_answer", ""),
    }


def _chapter_index(node_input: Any) -> int | None:
    """从节点输入推断本次要写第几章。

    重写时（validator 判定 retry_writer）以校验对象为准，否则为「下一个待写章节 + 1」。
    """
    if not isinstance(node_input, dict):
        return None

    validation = node_input.get("validation_result")
    if isinstance(validation, dict) and not validation.get("passed"):
        index = chapter_index_from_target(str(validation.get("target", "")))
        if index is not None:
            return index + 1

    sections = node_input.get("sections")
    if isinstance(sections, list):
        for index, section in enumerate(sections):
            if not (section.get("content") or "").strip():
                return index + 1
        return len(sections) + 1
    return None


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
        self._max_retries = max_retries

    @property
    def _config(self) -> dict[str, Any]:
        """图执行配置：给 LangGraph 足够大的超步上界（任务本身由预算约束）。"""
        return {"recursion_limit": recursion_limit(self._max_retries)}

    @property
    def max_retries(self) -> int:
        return self._max_retries

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
        final_state = await self._graph.ainvoke(state, config=self._config)
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
            async for event in self._graph.astream_events(state, version="v2", config=self._config):
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
                        if name == "validator":
                            validation = output.get("validation_result") or {}
                            payload["passed"] = bool(validation.get("passed"))
                            payload["target"] = validation.get("target")
                            payload["issues"] = validation.get("issues") or []
                            payload["suggested_action"] = validation.get("suggested_action")
                    yield _event(run_id, f"{name}_completed", **payload)

                    if name == "validator" and not payload.get("passed"):
                        yield _retrying_event(
                            run_id,
                            validation=output if isinstance(output, dict) else {},
                            max_retries=self._max_retries,
                        )
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
        except GraphRecursionError:
            # 兜底：即使超出安全上界，也要以可读事件结束，而不是中断 SSE（§20）
            logger.error(
                "图执行超出超步上限",
                extra={
                    "task_id": run_id,
                    "event": "task_failed",
                    "status": "error",
                    "error_type": "graph_recursion_limit",
                },
            )
            yield _event(
                run_id,
                "task_failed",
                status="error",
                message="任务步骤过多，已超出安全上限并终止",
                error_type="graph_recursion_limit",
            )
            return
        except Exception:
            # 未知异常：记录堆栈供排查，但不把细节返回给前端
            logger.exception(
                "任务执行出现未预期错误",
                extra={
                    "task_id": run_id,
                    "event": "task_failed",
                    "status": "error",
                    "error_type": "internal_error",
                },
            )
            yield _event(
                run_id,
                "task_failed",
                status="error",
                message="任务执行出现内部错误，请查看后端日志",
                error_type="internal_error",
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
            result=task_result(final_state, max_retries=self._max_retries),
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


def _retrying_event(
    task_id: str, *, validation: dict[str, Any], max_retries: int
) -> dict[str, Any]:
    """校验失败后推送 ``retrying`` 事件（§19）。"""
    result = validation.get("validation_result") or {}
    action = result.get("suggested_action")
    target = result.get("target") or "document"
    issues = result.get("issues") or []
    retry_counts = validation.get("retry_counts") or {}
    attempts = retry_counts.get(target, 0)
    exhausted = target != "document" and attempts >= max_retries

    if exhausted:
        message = f"{target} 已达重试上限（{max_retries} 次），跳过该章节并继续其他章节"
    elif action == "replan":
        message = f"校验未通过，重新规划任务（第 {validation.get('retry_count', 0)} 次重规划）"
    else:
        message = f"校验未通过，重写 {target}（第 {attempts} 次重试）"

    return _event(
        task_id,
        "retrying",
        status="running",
        message=message,
        step=target,
        suggested_action=action,
        issues=issues,
        retry_count=attempts,
        exhausted=exhausted,
    )
