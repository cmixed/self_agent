"""任务服务。

负责组装初始状态、调用 Agent Graph、整理结果。API 层不直接接触 Graph。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, cast
from uuid import uuid4

from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError

from app.agents.chapters import (
    MAX_SECTIONS,
    chapter_index_from_target,
    chapter_target,
    failed_chapters,
)
from app.agents.skills import CatalogEntry, pending_skill_step
from app.core.agent_graph import build_graph, recursion_limit
from app.core.errors import resolve_error
from app.core.limits import (
    DEFAULT_MAX_SECTIONS,
    DEFAULT_TARGET_SECTIONS,
    DEFAULT_TOTAL_CHARS,
)
from app.core.logging import get_logger
from app.core.task_registry import TaskRegistry, get_task_registry
from app.llm.base import LLMError, LLMProvider
from app.memory.repository import TaskRepository
from app.models.state import AgentState, RetrievalScope, RetrievedDocument, initial_state
from app.rag.tools import RagTool, dedupe_documents

logger = get_logger(__name__)


class TaskNotResumableError(Exception):
    """任务没有可用的检查点，无法「继续生成」（应改用重新生成）。"""

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
    """把检索结果整理为来源列表，编号与正文引用 [n] 严格对应。

    去重规则统一在 :func:`app.rag.tools.dedupe_documents`，与作家看到的
    ``format_context`` 和「参考来源」小节共用同一份编号。
    """
    sources: list[dict[str, Any]] = []
    for index, document in enumerate(dedupe_documents(documents), start=1):
        chunk_id = document.get("chunk_id", "")
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


def task_result(
    state: AgentState, *, max_retries: int, max_sections: int = MAX_SECTIONS
) -> dict[str, Any]:
    """把最终状态整理为 API 结果结构（TaskResponse 的字段集合）。"""
    failed = failed_chapters(state, max_retries=max_retries, max_sections=max_sections)
    scope = state.get("retrieval_scope") or None
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
        # 回显本次检索范围（标签 + 解析后的文档数），便于追溯与续跑确认
        "scope": (
            {
                "label": scope.get("label", ""),
                "document_count": len(scope.get("document_ids") or []),
                "category_ids": list(scope.get("category_ids") or []),
                "selected_document_ids": list(scope.get("selected_document_ids") or []),
            }
            if scope
            else None
        ),
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
    """运行一次 Agent 任务（可选持久化到 SQLite）。"""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        rag_tool_provider: Callable[[], RagTool] | None = None,
        skill_catalog: Sequence[CatalogEntry] | None = None,
        repository: TaskRepository | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        registry: TaskRegistry | None = None,
        max_retries: int = 2,
        target_sections: int = DEFAULT_TARGET_SECTIONS,
        max_sections: int = DEFAULT_MAX_SECTIONS,
        target_total_chars: int = DEFAULT_TOTAL_CHARS,
    ) -> None:
        self._catalog: list[CatalogEntry] = list(skill_catalog or [])
        self._max_sections = max(1, max_sections)
        self._graph = build_graph(
            llm,
            rag_tool_provider=rag_tool_provider,
            skill_catalog=self._catalog,
            checkpointer=checkpointer,
            max_retries=max_retries,
            target_sections=target_sections,
            max_sections=self._max_sections,
            target_total_chars=target_total_chars,
        )
        self._max_retries = max_retries
        self._repository = repository
        self._checkpointer = checkpointer
        self._registry = registry or get_task_registry()

    def _skill_name(self, skill_id: str | None) -> str:
        """技能名查表（用于 SSE 事件展示，不暴露技能正文）。"""
        for entry in self._catalog:
            if entry["skill_id"] == skill_id:
                return entry["name"]
        return skill_id or ""

    def _config_for(self, run_id: str) -> RunnableConfig:
        """图执行配置：超步上界 + （启用 Checkpoint 时）线程 id。"""
        config: RunnableConfig = {
            "recursion_limit": recursion_limit(
                self._max_retries, max_sections=self._max_sections
            )
        }
        if self._checkpointer is not None:
            config["configurable"] = {"thread_id": run_id}
        return config

    @property
    def _config(self) -> RunnableConfig:
        """不含 thread_id 的默认配置（兼容旧用法 / 测试）。"""
        return self._config_for("")

    @property
    def max_retries(self) -> int:
        return self._max_retries

    async def run(
        self,
        query: str,
        *,
        user_preferences: dict[str, str] | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        retrieval_scope: RetrievalScope | None = None,
    ) -> AgentState:
        """同步执行入口：登记运行中的任务，使 /cancel 能精确取消。"""
        run_id = task_id or str(uuid4())
        self._registry.register(run_id, asyncio.current_task())
        try:
            return await self._run_impl(
                query,
                user_preferences=user_preferences,
                task_id=run_id,
                user_id=user_id,
                retrieval_scope=retrieval_scope,
            )
        except asyncio.CancelledError:
            await self._mark_cancelled(run_id)
            raise
        finally:
            self._registry.unregister(run_id)

    async def _run_impl(
        self,
        query: str,
        *,
        user_preferences: dict[str, str] | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        retrieval_scope: RetrievalScope | None = None,
    ) -> AgentState:
        run_id = task_id or str(uuid4())
        state = initial_state(
            query,
            task_id=run_id,
            user_preferences=user_preferences,
            retrieval_scope=retrieval_scope,
        )

        logger.info(
            "任务开始",
            extra={"task_id": run_id, "event": "task_started", "status": "running"},
        )
        await self._start_run(run_id, query, user_id)
        try:
            final_state = cast(
                AgentState,
                await self._graph.ainvoke(state, config=self._config_for(run_id)),
            )
        except Exception as exc:
            await self._fail_run(run_id, exc)
            raise

        logger.info(
            "任务结束",
            extra={
                "task_id": run_id,
                "event": "task_finished",
                "status": final_state.get("task_status", "unknown"),
            },
        )
        await self._finish_run(run_id, final_state)
        return final_state

    # --- 持久化辅助（未配置仓储时全部为 no-op）---

    async def _start_run(self, run_id: str, query: str, user_id: str | None) -> None:
        if self._repository is None:
            return
        await self._repository.start_run(
            task_id=run_id, user_id=user_id or "local-user", query=query
        )

    async def _finish_run(self, run_id: str, state: AgentState) -> None:
        if self._repository is None:
            return
        await self._repository.finish_run(
            task_id=run_id,
            result=task_result(
                state, max_retries=self._max_retries, max_sections=self._max_sections
            ),
        )

    async def _mark_cancelled(self, run_id: str) -> None:
        """取消时落库：把一个仍在运行的 run 标记为 cancelled。

        用 asyncio.shield 保证清理不被同一次取消打断。
        """
        if self._repository is None:
            return
        logger.warning(
            "任务被取消",
            extra={"task_id": run_id, "event": "task_cancelled", "status": "cancelled"},
        )
        with contextlib.suppress(Exception):
            await asyncio.shield(self._repository.cancel_run(task_id=run_id))

    async def _fail_run(self, run_id: str, exc: BaseException) -> None:
        if self._repository is None:
            return
        error_type = getattr(exc, "error_type", None) or type(exc).__name__
        await self._repository.fail_run(task_id=run_id, error_type=str(error_type))

    async def stream(
        self,
        query: str,
        *,
        user_preferences: dict[str, str] | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        retrieval_scope: RetrievalScope | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE 入口：登记运行中的任务；被取消时标记为 cancelled 再向上抛出。"""
        run_id = task_id or str(uuid4())
        self._registry.register(run_id, asyncio.current_task())
        try:
            async for event in self._stream_impl(
                query,
                user_preferences=user_preferences,
                task_id=run_id,
                user_id=user_id,
                retrieval_scope=retrieval_scope,
            ):
                yield event
        except asyncio.CancelledError:
            await self._mark_cancelled(run_id)
            raise
        finally:
            self._registry.unregister(run_id)

    async def _stream_impl(
        self,
        query: str,
        *,
        user_preferences: dict[str, str] | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        retrieval_scope: RetrievalScope | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """按 §19 协议逐条产出进度事件。

        错误不向外抛出，而是转换为 ``task_failed`` 事件，保证 SSE 连接
        能正常结束并给出可读信息。
        """
        run_id = task_id or str(uuid4())
        state = initial_state(
            query,
            task_id=run_id,
            user_preferences=user_preferences,
            retrieval_scope=retrieval_scope,
        )

        await self._start_run(run_id, query, user_id)
        yield _event(run_id, "task_started", status="running", message="任务已创建")

        async for event in self._run_graph(run_id, state):
            yield event

    async def resume(
        self,
        task_id: str,
        *,
        user_preferences: dict[str, str] | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """从断点继续执行（同一 task_id 与 checkpoint thread）。

        失败/取消发生在某个节点内部时，检查点停在**上一个超步**，因此续跑会
        恰好从失败的那个节点重新开始：已完成的章节不重写、不重复计费。
        """
        self._registry.register(task_id, asyncio.current_task())
        try:
            async for event in self._resume_impl(
                task_id, user_preferences=user_preferences, user_id=user_id
            ):
                yield event
        except asyncio.CancelledError:
            await self._mark_cancelled(task_id)
            raise
        finally:
            self._registry.unregister(task_id)

    async def _resume_impl(
        self,
        task_id: str,
        *,
        user_preferences: dict[str, str] | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        snapshot = await self.snapshot(task_id)
        if snapshot is None:
            raise TaskNotResumableError("该任务没有可恢复的检查点，请使用「重新生成」")

        if self._repository is not None:
            await self._repository.resume_run(task_id=task_id)

        written = len([s for s in snapshot.get("sections") or [] if s.get("content")])
        outline = [str(s.get("title", "")) for s in snapshot.get("outline") or []]
        documents = snapshot.get("retrieved_documents") or []
        yield _event(
            task_id,
            "task_resumed",
            status="running",
            message=(
                f"已从断点继续（已完成 {written}/{len(outline)} 章）"
                if outline
                else "已从断点继续"
            ),
            resumed=True,
            plan=snapshot.get("plan"),
            scope=snapshot.get("retrieval_scope"),
            outline=outline,
            chapters_written=written,
            retrieved_count=len(documents),
            sources=_sources(documents),
        )

        # 输入为 None：LangGraph 从该 thread 的最后一个检查点继续
        async for event in self._run_graph(task_id, None):
            yield event

    async def snapshot(self, task_id: str) -> dict[str, Any] | None:
        """读取该任务最近一次 checkpoint 的状态值（无则 None）。"""
        if self._checkpointer is None:
            return None
        checkpoint_tuple = await self._checkpointer.aget_tuple(
            {"configurable": {"thread_id": task_id}}
        )
        if checkpoint_tuple is None:
            return None
        checkpoint = checkpoint_tuple.checkpoint or {}
        values = checkpoint.get("channel_values")
        return values if isinstance(values, dict) else {}

    async def _run_graph(
        self, run_id: str, graph_input: AgentState | None
    ) -> AsyncIterator[dict[str, Any]]:
        """执行/续跑图并按 §19 产出事件；错误转为 ``task_failed``，不向外抛。"""
        final_state: AgentState = graph_input if graph_input is not None else AgentState()
        try:
            async for event in self._graph.astream_events(
                graph_input, version="v2", config=self._config_for(run_id)
            ):
                name = event.get("name")
                kind = event.get("event")

                if name == "LangGraph" and kind == "on_chain_end":
                    output = (event.get("data") or {}).get("output")
                    if isinstance(output, dict):
                        final_state = cast(AgentState, output)
                    continue

                if name == "skills":
                    # 技能节点每次执行一个技能步骤：逐技能推送事件（§19 扩展）。
                    # 无待执行技能时该节点是空转（拓扑上必经一次），不推送空事件。
                    if kind == "on_chain_start":
                        step = pending_skill_step((event.get("data") or {}).get("input") or {})
                        if step is None:
                            continue
                        skill_id = str(step.get("skill_id") or "")
                        yield _event(
                            run_id,
                            "skill_started",
                            status="running",
                            message=f"正在应用技能「{self._skill_name(skill_id)}」",
                            step=str(step.get("id")) if step else None,
                            skill_id=skill_id,
                            skill_name=self._skill_name(skill_id),
                        )
                    elif kind == "on_chain_end":
                        output = (event.get("data") or {}).get("output") or {}
                        outputs = output.get("skill_outputs") or []
                        if not outputs:
                            continue
                        latest = outputs[-1]
                        skill_id = str(latest.get("skill_id") or "")
                        yield _event(
                            run_id,
                            "skill_completed",
                            status="ok",
                            message=(
                                f"技能「{latest.get('skill_name') or self._skill_name(skill_id)}」"
                                "执行完成"
                            ),
                            step=str(latest.get("step_id") or "") or None,
                            skill_id=skill_id,
                            skill_name=latest.get("skill_name") or self._skill_name(skill_id),
                            summary=latest.get("summary") or "",
                        )
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
                            documents = output.get("retrieved_documents") or []
                            payload["retrieved_count"] = len(documents)
                            # 增量附带去重后的来源明细（与最终 result.sources 同源同编号），
                            # 使前端在运行中即可展示「检索到的资料」。不修改既有字段。
                            payload["sources"] = _sources(documents)
                        if name == "outline":
                            payload["outline"] = [
                                section.get("title", "")
                                for section in (output.get("outline") or [])
                            ]
                            # 章节被上限截断时，把说明并入完成消息（前端进度日志可见）
                            for step_result in output.get("step_results") or []:
                                step_summary = str(step_result.get("summary") or "")
                                if "截断" in step_summary:
                                    payload["message"] = step_summary
                                    payload["truncated"] = True
                        if name == "writer":
                            payload["step"] = output.get("current_step") or name
                            # 章节被输出长度上限截断时，让进度消息如实说明
                            for step_result in output.get("step_results") or []:
                                step_summary = str(step_result.get("summary") or "")
                                if "截断" in step_summary:
                                    payload["message"] = step_summary
                                    payload["truncated"] = True
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
            await self._fail_run(run_id, exc)
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
        except GraphRecursionError as exc:
            # 兜底：即使超出安全上界，也要以可读事件结束，而不是中断 SSE（§20）
            await self._fail_run(run_id, exc)
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
        except Exception as exc:
            # 未知异常：记录堆栈供排查，但不把细节返回给前端
            await self._fail_run(run_id, exc)
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
            final_state["final_answer"] = final_state.get("final_answer", "")
            await self._finish_run(run_id, final_state)
            yield _event(run_id, "task_failed", status="error", message="任务未能正常完成")
            return

        logger.info(
            "任务结束",
            extra={"task_id": run_id, "event": "task_completed", "status": "completed"},
        )
        await self._finish_run(run_id, final_state)
        yield _event(
            run_id,
            "task_completed",
            status="completed",
            message="任务完成",
            result=task_result(
                final_state, max_retries=self._max_retries, max_sections=self._max_sections
            ),
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
