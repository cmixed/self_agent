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
from app.llm.usage import UsageCollector, UsageTrackingProvider, collect_usage
from app.memory.repository import TaskRepository
from app.models.state import (
    AgentState,
    RetrievalMode,
    RetrievalScope,
    RetrievedDocument,
    StepResult,
    UserMemory,
    initial_state,
)
from app.models.task_profile import resolve_profile
from app.rag.tools import RagTool, dedupe_documents
from app.services.verbatim_service import (
    VerbatimDocumentNotFoundError,
    VerbatimDocumentTooLargeError,
    VerbatimError,
    VerbatimNoDocumentError,
    VerbatimService,
    VerbatimUnavailableError,
    render_verbatim_document,
    verbatim_summary,
)

logger = get_logger(__name__)


class TaskNotResumableError(Exception):
    """任务没有可用的检查点，无法「继续生成」（应改用重新生成）。"""


# 节点 -> (进行中提示, 完成提示)。仅这些节点会推送给前端（§19）。
_NODE_EVENTS: dict[str, tuple[str, str]] = {
    "answer": ("正在生成回答", "回答已生成"),
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
    state: AgentState,
    *,
    max_retries: int,
    max_sections: int = MAX_SECTIONS,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把最终状态整理为 API 结果结构（TaskResponse 的字段集合）。"""
    failed = failed_chapters(state, max_retries=max_retries, max_sections=max_sections)
    scope = state.get("retrieval_scope") or None
    profile = state.get("task_profile") or {}
    verbatim_outputs = list(state.get("verbatim_outputs") or [])
    output_mode = str(profile.get("output_mode") or "generate")
    return {
        "task_id": state.get("task_id", ""),
        "status": state.get("task_status", "failed"),
        # 本次任务采用的执行模式（direct / brief / longform / verbatim）与完整画像，
        # 供前端展示「轻量回答」或「长文流水线」，也便于评估时分组统计。
        "mode": profile.get("mode"),
        "profile": profile or None,
        "output_mode": output_mode,
        "verbatim": verbatim_summary(verbatim_outputs[0] if verbatim_outputs else None),
        "plan": state.get("plan"),
        "writing_budget": state.get("writing_budget"),
        "outline": [section.get("title", "") for section in (state.get("outline") or [])],
        "step_results": state.get("step_results", []),
        "sources": _sources(state.get("retrieved_documents") or []),
        "validation": state.get("validation_result"),
        "retry_count": state.get("retry_count", 0),
        "failed_chapters": [chapter_target(index) for index in failed],
        "final_answer": state.get("final_answer", ""),
        # 本次运行的用量（token / 缓存命中 / 速度）；由 Provider 装饰器采集
        "usage": usage,
        # 检索模式：all / selected / none；旧任务可能缺省
        "retrieval_mode": state.get("retrieval_mode") or "all",
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
        verbatim_provider: Callable[[LLMProvider], VerbatimService] | None = None,
        repository: TaskRepository | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        registry: TaskRegistry | None = None,
        max_retries: int = 2,
        target_sections: int = DEFAULT_TARGET_SECTIONS,
        max_sections: int = DEFAULT_MAX_SECTIONS,
        target_total_chars: int = DEFAULT_TOTAL_CHARS,
        default_depth: str = "auto",
    ) -> None:
        self._catalog: list[CatalogEntry] = list(skill_catalog or [])
        self._max_sections = max(1, max_sections)
        self._target_total_chars = target_total_chars
        self._default_depth = default_depth
        # 统一在 Provider 外层计量：Agent 节点只关心业务，不感知用量统计
        self._llm = UsageTrackingProvider(llm)
        # 原文选择也走同一个计量 Provider；显式指定文档时不会产生 LLM 调用。
        self._verbatim = verbatim_provider(self._llm) if verbatim_provider else None
        self._last_usage: dict[str, Any] | None = None
        self._graph = build_graph(
            self._llm,
            rag_tool_provider=rag_tool_provider,
            skill_catalog=self._catalog,
            verbatim_provider=(lambda: self._verbatim) if self._verbatim is not None else None,
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
            "recursion_limit": recursion_limit(self._max_retries, max_sections=self._max_sections)
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

    @property
    def last_usage(self) -> dict[str, Any] | None:
        """最近一次运行的用量（同步入口用它补齐 API 响应中的 usage）。"""
        return self._last_usage

    def _profile_for(
        self,
        query: str,
        *,
        depth: str | None,
        use_skills: bool | None,
        retrieval_mode: RetrievalMode | None = None,
    ):
        """解析任务画像（0 次 LLM 调用）。"""
        return resolve_profile(
            query,
            depth=(depth or self._default_depth),
            use_skills=bool(use_skills),
            target_total_chars=self._target_total_chars,
            max_sections=self._max_sections,
            retrieval_mode=retrieval_mode or "all",
        )

    async def run(
        self,
        query: str,
        *,
        user_preferences: dict[str, str] | None = None,
        user_memories: list[UserMemory] | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        retrieval_scope: RetrievalScope | None = None,
        retrieval_mode: RetrievalMode | None = None,
        depth: str | None = None,
        use_skills: bool | None = None,
    ) -> AgentState:
        """同步执行入口：登记运行中的任务，使 /cancel 能精确取消。"""
        run_id = task_id or str(uuid4())
        self._registry.register(run_id, asyncio.current_task())
        try:
            return await self._run_impl(
                query,
                user_preferences=user_preferences,
                user_memories=user_memories,
                task_id=run_id,
                user_id=user_id,
                retrieval_scope=retrieval_scope,
                retrieval_mode=retrieval_mode,
                depth=depth,
                use_skills=use_skills,
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
        user_memories: list[UserMemory] | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        retrieval_scope: RetrievalScope | None = None,
        retrieval_mode: RetrievalMode | None = None,
        depth: str | None = None,
        use_skills: bool | None = None,
    ) -> AgentState:
        run_id = task_id or str(uuid4())
        profile = self._profile_for(
            query, depth=depth, use_skills=use_skills, retrieval_mode=retrieval_mode
        )
        state = initial_state(
            query,
            task_id=run_id,
            user_preferences=user_preferences,
            user_memories=user_memories,
            retrieval_scope=retrieval_scope,
            retrieval_mode=retrieval_mode,
            task_profile=profile.to_dict(),
        )

        logger.info(
            "任务开始",
            extra={
                "task_id": run_id,
                "event": "task_started",
                "status": "running",
                "mode": profile.mode,
            },
        )
        await self._start_run(run_id, query, user_id)
        self._last_usage = None
        with collect_usage() as usage:
            try:
                final_state = cast(
                    AgentState,
                    await self._graph.ainvoke(state, config=self._config_for(run_id)),
                )
            except Exception as exc:
                await self._fail_run(run_id, exc)
                raise
        self._last_usage = usage.to_dict()

        logger.info(
            "任务结束",
            extra={
                "task_id": run_id,
                "event": "task_finished",
                "status": final_state.get("task_status", "unknown"),
            },
        )
        await self._finish_run(run_id, final_state, usage=self._last_usage)
        return final_state

    # --- 直接输出知识库原文（不经过 Agent Graph）---

    def _verbatim_state(
        self,
        run_id: str,
        query: str,
        *,
        retrieval_scope: RetrievalScope | None,
        retrieval_mode: RetrievalMode | None,
    ) -> AgentState:
        state = initial_state(
            query,
            task_id=run_id,
            retrieval_scope=retrieval_scope,
            retrieval_mode=retrieval_mode,
            task_profile={
                "mode": "verbatim",
                "output_mode": "verbatim",
                "needs_retrieval": True,
                "target_chars": 0,
                "max_sections": 1,
                "validation": "none",
                "apply_preferences": "none",
                "allow_skills": False,
                "reason": "直接输出知识库原文",
            },
        )
        return state

    async def _resolve_verbatim(
        self,
        query: str,
        *,
        document_id: str | None,
        retrieval_scope: RetrievalScope | None,
        retrieval_mode: RetrievalMode | None,
    ) -> dict:
        if self._verbatim is None:
            raise VerbatimUnavailableError("原文输出服务未配置")
        scope = retrieval_scope or None
        scope_ids = scope.get("document_ids") if scope else None
        output = await self._verbatim.resolve_direct(
            query,
            document_id=document_id,
            scope_ids=scope_ids,
            retrieval_mode=str(retrieval_mode or "all"),
        )
        return dict(output)

    async def run_verbatim(
        self,
        query: str,
        *,
        document_id: str | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        retrieval_scope: RetrievalScope | None = None,
        retrieval_mode: RetrievalMode | None = None,
    ) -> AgentState:
        """同步执行「直接输出原文」：不进入 Graph，不写 checkpoint。"""
        run_id = task_id or str(uuid4())
        self._registry.register(run_id, asyncio.current_task())
        try:
            state = self._verbatim_state(
                run_id,
                query,
                retrieval_scope=retrieval_scope,
                retrieval_mode=retrieval_mode,
            )
            await self._start_run(run_id, query, user_id, output_mode="verbatim")
            self._last_usage = None
            try:
                with collect_usage() as usage:
                    output = await self._resolve_verbatim(
                        query,
                        document_id=document_id,
                        retrieval_scope=retrieval_scope,
                        retrieval_mode=retrieval_mode,
                    )
                self._last_usage = usage.to_dict()
            except Exception as exc:
                await self._fail_run(run_id, exc, error_type=_verbatim_error_type(exc))
                raise
            state["verbatim_outputs"] = [output]  # type: ignore[list-item]
            state["final_answer"] = render_verbatim_document(output)  # type: ignore[arg-type]
            state["task_status"] = "completed"
            state["is_complete"] = True
            state["step_results"] = [
                StepResult(
                    step_id="verbatim",
                    status="ok",
                    summary=(
                        f"已直接输出《{output.get('filename', '')}》原文"
                        f"（约 {output.get('chars', 0)} 字）"
                    ),
                )
            ]
            await self._finish_run(run_id, state, usage=self._last_usage)
            return state
        except asyncio.CancelledError:
            await self._mark_cancelled(run_id)
            raise
        finally:
            self._registry.unregister(run_id)

    async def stream_verbatim(
        self,
        query: str,
        *,
        document_id: str | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        retrieval_scope: RetrievalScope | None = None,
        retrieval_mode: RetrievalMode | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE 版直接原文输出：只推送查找 / 读取两步，不展示写作流水线。"""
        run_id = task_id or str(uuid4())
        self._registry.register(run_id, asyncio.current_task())
        try:
            async for event in self._stream_verbatim_impl(
                run_id,
                query,
                document_id=document_id,
                user_id=user_id,
                retrieval_scope=retrieval_scope,
                retrieval_mode=retrieval_mode,
            ):
                yield event
        except asyncio.CancelledError:
            await self._mark_cancelled(run_id)
            raise
        finally:
            self._registry.unregister(run_id)

    async def _stream_verbatim_impl(
        self,
        run_id: str,
        query: str,
        *,
        document_id: str | None,
        user_id: str | None,
        retrieval_scope: RetrievalScope | None,
        retrieval_mode: RetrievalMode | None,
    ) -> AsyncIterator[dict[str, Any]]:
        state = self._verbatim_state(
            run_id,
            query,
            retrieval_scope=retrieval_scope,
            retrieval_mode=retrieval_mode,
        )
        await self._start_run(run_id, query, user_id, output_mode="verbatim")
        yield _event(
            run_id,
            "task_started",
            status="running",
            message="正在直接输出知识库原文",
            mode="verbatim",
            profile=state.get("task_profile"),
            retrieval_mode=retrieval_mode or "all",
            output_mode="verbatim",
        )
        yield _event(
            run_id,
            "verbatim_started",
            status="running",
            message="正在查找最合适的知识库文档",
        )
        self._last_usage = None
        try:
            with collect_usage() as usage:
                output = await self._resolve_verbatim(
                    query,
                    document_id=document_id,
                    retrieval_scope=retrieval_scope,
                    retrieval_mode=retrieval_mode,
                )
            self._last_usage = usage.to_dict()
        except Exception as exc:
            error_type = _verbatim_error_type(exc)
            await self._fail_run(run_id, exc, error_type=error_type)
            logger.warning(
                "直接输出原文失败",
                extra={
                    "task_id": run_id,
                    "event": "verbatim_failed",
                    "status": "error",
                    "error_type": error_type,
                },
            )
            yield _event(
                run_id,
                "task_failed",
                status="error",
                message=str(exc) or "无法输出知识库原文",
                error_type=error_type,
            )
            return

        yield _event(
            run_id,
            "verbatim_completed",
            status="ok",
            message=(
                f"已读取《{output.get('filename', '')}》原文（约 {output.get('chars', 0)} 字）"
            ),
            document_id=output.get("document_id", ""),
            filename=output.get("filename", ""),
            chars=output.get("chars", 0),
            selection=output.get("selection", ""),
            reason=output.get("reason", ""),
        )
        state["verbatim_outputs"] = [output]  # type: ignore[list-item]
        state["final_answer"] = render_verbatim_document(output)  # type: ignore[arg-type]
        state["task_status"] = "completed"
        state["is_complete"] = True
        state["step_results"] = [
            StepResult(
                step_id="verbatim",
                status="ok",
                summary=(
                    f"已直接输出《{output.get('filename', '')}》原文"
                    f"（约 {output.get('chars', 0)} 字）"
                ),
            )
        ]
        await self._finish_run(run_id, state, usage=self._last_usage)
        yield _event(
            run_id,
            "task_completed",
            status="completed",
            message="任务完成",
            result=task_result(
                state,
                max_retries=self._max_retries,
                max_sections=self._max_sections,
                usage=self._last_usage,
            ),
        )

    # --- 持久化辅助（未配置仓储时全部为 no-op）---

    async def _start_run(
        self,
        run_id: str,
        query: str,
        user_id: str | None,
        *,
        output_mode: str = "generate",
    ) -> None:
        if self._repository is None:
            return
        await self._repository.start_run(
            task_id=run_id,
            user_id=user_id or "local-user",
            query=query,
            output_mode=output_mode,
        )

    async def _finish_run(
        self,
        run_id: str,
        state: AgentState,
        *,
        usage: dict[str, Any] | None = None,
    ) -> None:
        self._last_usage = usage
        if self._repository is None:
            return
        await self._repository.finish_run(
            task_id=run_id,
            result=task_result(
                state,
                max_retries=self._max_retries,
                max_sections=self._max_sections,
                usage=usage,
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

    async def _fail_run(
        self,
        run_id: str,
        exc: BaseException,
        *,
        error_type: str | None = None,
    ) -> None:
        if self._repository is None:
            return
        resolved = error_type or getattr(exc, "error_type", None) or type(exc).__name__
        await self._repository.fail_run(task_id=run_id, error_type=str(resolved))

    async def stream(
        self,
        query: str,
        *,
        user_preferences: dict[str, str] | None = None,
        user_memories: list[UserMemory] | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        retrieval_scope: RetrievalScope | None = None,
        retrieval_mode: RetrievalMode | None = None,
        depth: str | None = None,
        use_skills: bool | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE 入口：登记运行中的任务；被取消时标记为 cancelled 再向上抛出。"""
        run_id = task_id or str(uuid4())
        self._registry.register(run_id, asyncio.current_task())
        try:
            async for event in self._stream_impl(
                query,
                user_preferences=user_preferences,
                user_memories=user_memories,
                task_id=run_id,
                user_id=user_id,
                retrieval_scope=retrieval_scope,
                retrieval_mode=retrieval_mode,
                depth=depth,
                use_skills=use_skills,
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
        user_memories: list[UserMemory] | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        retrieval_scope: RetrievalScope | None = None,
        retrieval_mode: RetrievalMode | None = None,
        depth: str | None = None,
        use_skills: bool | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """按 §19 协议逐条产出进度事件。

        错误不向外抛出，而是转换为 ``task_failed`` 事件，保证 SSE 连接
        能正常结束并给出可读信息。
        """
        run_id = task_id or str(uuid4())
        profile = self._profile_for(
            query, depth=depth, use_skills=use_skills, retrieval_mode=retrieval_mode
        )
        state = initial_state(
            query,
            task_id=run_id,
            user_preferences=user_preferences,
            user_memories=user_memories,
            retrieval_scope=retrieval_scope,
            retrieval_mode=retrieval_mode,
            task_profile=profile.to_dict(),
        )

        await self._start_run(run_id, query, user_id)
        yield _event(
            run_id,
            "task_started",
            status="running",
            message=f"任务已创建（{'长文' if profile.mode == 'longform' else '轻量回答'}模式）",
            mode=profile.mode,
            profile=profile.to_dict(),
            retrieval_mode=retrieval_mode or "all",
        )

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
        profile = snapshot.get("task_profile") or {}
        yield _event(
            task_id,
            "task_resumed",
            status="running",
            message=(
                f"已从断点继续（已完成 {written}/{len(outline)} 章）" if outline else "已从断点继续"
            ),
            resumed=True,
            plan=snapshot.get("plan"),
            writing_budget=snapshot.get("writing_budget"),
            scope=snapshot.get("retrieval_scope"),
            outline=outline,
            chapters_written=written,
            retrieved_count=len(documents),
            sources=_sources(documents),
            mode=profile.get("mode"),
            profile=profile or None,
            retrieval_mode=snapshot.get("retrieval_mode") or "all",
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
        """为整次运行开一个用量作用域（新建与续跑共用）。"""
        self._last_usage = None
        with collect_usage() as usage:
            async for event in self._run_graph_events(run_id, graph_input, usage=usage):
                yield event
            self._last_usage = usage.to_dict()

    async def _run_graph_events(
        self,
        run_id: str,
        graph_input: AgentState | None,
        *,
        usage: UsageCollector,
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
                            if output.get("writing_budget"):
                                payload["writing_budget"] = output["writing_budget"]
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
            await self._finish_run(run_id, final_state, usage=usage.to_dict())
            yield _event(run_id, "task_failed", status="error", message="任务未能正常完成")
            return

        logger.info(
            "任务结束",
            extra={"task_id": run_id, "event": "task_completed", "status": "completed"},
        )
        await self._finish_run(run_id, final_state, usage=usage.to_dict())
        yield _event(
            run_id,
            "task_completed",
            status="completed",
            message="任务完成",
            result=task_result(
                final_state,
                max_retries=self._max_retries,
                max_sections=self._max_sections,
                usage=usage.to_dict(),
            ),
        )


def _verbatim_error_type(exc: BaseException) -> str:
    """把原文输出异常映射为前端可识别的错误码。"""
    if isinstance(exc, VerbatimUnavailableError):
        return "verbatim_unavailable"
    if isinstance(exc, VerbatimNoDocumentError):
        return "verbatim_no_document"
    if isinstance(exc, VerbatimDocumentNotFoundError):
        return "verbatim_document_not_found"
    if isinstance(exc, VerbatimDocumentTooLargeError):
        return "verbatim_document_too_large"
    if isinstance(exc, VerbatimError):
        return "verbatim_failed"
    return "internal_error"


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
