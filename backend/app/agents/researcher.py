"""Researcher 节点。

通过 RAG Tool 检索个人知识库，把结果写入 ``retrieved_documents``（AGENTS.md §11）。
Phase 3B 采用单次检索：以用户任务（拼接计划目标）作为检索 query。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.core.logging import get_logger
from app.embedding.base import EmbeddingError
from app.llm.base import ChatMessage
from app.models.state import AgentState, StepResult
from app.rag.loader import DocumentError
from app.rag.tools import RagTool

logger = get_logger(__name__)


def make_researcher_node(
    tool_provider: Callable[[], RagTool],
    *,
    top_k: int | None = None,
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造 researcher 节点。

    ``tool_provider`` 延迟创建 RAG Tool，避免不需要检索的任务也去加载
    Embedding 模型。
    """

    async def researcher_node(state: AgentState) -> dict:
        if state.get("retrieval_mode") == "none":
            # 正常路由不会到这里；防御性地跳过，避免用户明确关闭检索后仍加载模型
            return {"retrieved_documents": [], "task_status": "writing"}

        query = _build_query(state)

        try:
            # RAG Tool 的构造可能触发 Embedding 模型加载：放到线程里，避免阻塞事件循环
            tool = await asyncio.to_thread(tool_provider)
            scope = state.get("retrieval_scope") or {}
            documents = await tool.search(
                query,
                top_k=top_k,
                document_ids=scope.get("document_ids"),
            )
        except (EmbeddingError, DocumentError) as exc:
            # 检索失败不终止任务：记录可见的错误状态，降级为仅用通用知识作答（§20）
            logger.warning(
                "知识库检索失败",
                extra={
                    "task_id": state.get("task_id"),
                    "node": "researcher",
                    "event": "retrieval_failed",
                    "status": "error",
                    "error_type": getattr(exc, "error_type", "unknown"),
                },
            )
            return {
                "retrieved_documents": [],
                "current_step": "research",
                "task_status": "writing",
                "messages": [
                    ChatMessage(
                        role="assistant",
                        content="[researcher] 知识库检索失败，改为仅依据通用知识作答",
                    )
                ],
                "step_results": [
                    StepResult(
                        step_id="research",
                        status="error",
                        summary=f"知识库检索失败：{getattr(exc, 'error_type', 'error')}",
                    )
                ],
            }

        logger.info(
            "researcher 完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "researcher",
                "event": "retrieval_completed",
                "status": "ok",
            },
        )
        return {
            "retrieved_documents": documents,
            "current_step": "research",
            "task_status": "writing",
            "messages": [
                ChatMessage(
                    role="assistant",
                    content=f"[researcher] 检索到 {len(documents)} 条相关片段",
                )
            ],
            "step_results": [
                StepResult(
                    step_id="research",
                    status="ok",
                    summary=f"检索到 {len(documents)} 条相关片段",
                )
            ],
        }

    return researcher_node


def _build_query(state: AgentState) -> str:
    query = state.get("user_query", "")
    plan = state.get("plan")
    if plan and plan.get("goal"):
        return f"{query}\n{plan['goal']}"
    return query
