"""轻量回答节点（direct / brief）。

背景：过去所有任务都会进入「Planner → 大纲 → 逐章写作 → 逐章校验」，
连「你好」也要十几次模型调用。现在由 TaskProfile 把简单任务路由到这里：

- ``direct``：单次回答，不检索、不生成章节、不校验；
- ``brief``：单次回答，可选检索知识库；只做一次确定性的引用编号检查，
  必要时最多再修复一次（不调用 Validator、不触发 replan）。

RAG 仍然只通过 ``RagTool`` 访问（AGENTS.md §4.1），本节点不碰 Chroma。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from app.agents.base import AgentNode
from app.agents.citations import citation_issue_text, dangling_citation_indices
from app.agents.memory_context import render_memories
from app.agents.preferences import render_preferences
from app.core.coerce import as_int
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMError, LLMProvider, LLMUpstreamError
from app.llm.thinking import thinking_scope
from app.models.state import AgentState, Plan, PlanStep, RetrievedDocument, StepResult
from app.prompts import render_prompt
from app.rag.loader import DocumentError
from app.rag.tools import RagTool, dedupe_documents, format_context, render_references

logger = get_logger(__name__)


def make_answer_node(
    llm: LLMProvider,
    *,
    rag_tool_provider: Callable[[], RagTool] | None = None,
) -> AgentNode:
    """构造轻量回答节点。"""

    # 本地小模型上下文更小：记忆预算减半，避免挤占 num_ctx
    compact_memory = bool(getattr(llm, "is_local", False))

    async def answer_node(state: AgentState) -> dict:
        profile = state.get("task_profile") or {}
        mode = str(profile.get("mode") or "brief")
        # 缺失 / 0 / 非数字一律回退 900（state 值来自 checkpoint，静态只是 object）
        target_chars = as_int(profile.get("target_chars"), 0) or 900
        query = state.get("user_query", "")

        step_results: list[StepResult] = []
        documents: list[RetrievedDocument] = list(state.get("retrieved_documents") or [])

        # brief 可选检索；direct 按定义不检索。检索失败降级为通用知识，不终止任务。
        if (
            mode == "brief"
            and profile.get("needs_retrieval")
            and rag_tool_provider is not None
            and not documents
        ):
            try:
                tool = await asyncio.to_thread(rag_tool_provider)
                scope = state.get("retrieval_scope") or {}
                documents = await tool.search(query, document_ids=scope.get("document_ids"))
                step_results.append(
                    StepResult(
                        step_id="research",
                        status="ok",
                        summary=f"检索到 {len(documents)} 条相关片段",
                    )
                )
            except (LLMError, DocumentError) as exc:
                logger.warning(
                    "轻量回答检索失败，降级为通用知识",
                    extra={
                        "task_id": state.get("task_id"),
                        "node": "answer",
                        "event": "retrieval_failed",
                        "status": "error",
                        "error_type": getattr(exc, "error_type", "unknown"),
                    },
                )
                step_results.append(
                    StepResult(
                        step_id="research",
                        status="error",
                        summary=f"知识库检索失败：{getattr(exc, 'error_type', 'error')}",
                    )
                )
            except Exception as exc:  # 检索层异常不应让简单任务失败
                logger.warning(
                    "轻量回答检索异常，降级为通用知识",
                    extra={
                        "task_id": state.get("task_id"),
                        "node": "answer",
                        "event": "retrieval_failed",
                        "status": "error",
                        "error_type": type(exc).__name__,
                    },
                )
                step_results.append(
                    StepResult(
                        step_id="research",
                        status="error",
                        summary="知识库检索失败，已改用通用知识",
                    )
                )

        messages = _build_messages(
            state,
            mode=mode,
            target_chars=target_chars,
            documents=documents,
            compact=compact_memory,
        )
        # 轻量任务关闭思考模式：推理 token 会挤占输出预算并显著增加延迟。
        with thinking_scope(False):
            response = await llm.chat(
                messages,
                temperature=0.3,
                # 软目标 + 安全网：正常不会触发；触发时在 step_result 中如实标注。
                max_tokens=max(512, min(4096, target_chars * 2)),
            )
        content = response.content.strip()
        if not content:
            raise LLMUpstreamError("模型未返回正文（可能是思考模式占用了输出预算）")

        # 引用编号是机械可判定的事实：只做一次确定性检查 + 最多一次修复。
        repaired = False
        if mode == "brief" and profile.get("validation") == "citation_only":
            content, repaired = await _repair_citations(llm, messages, content, documents=documents)

        final_answer = content
        references = render_references(documents, heading=False)
        if references:
            final_answer = f"{final_answer}\n\n{references}"

        summary = f"已生成{('简洁' if mode == 'brief' else '直接')}回答（{len(final_answer)} 字）"
        if repaired:
            summary += "，引用编号已修复"
        if response.finish_reason == "length":
            summary += "（输出达到长度上限，内容可能被截断）"
        step_results.append(
            StepResult(
                step_id="answer",
                status="ok" if response.finish_reason != "length" else "error",
                summary=summary,
            )
        )

        plan: Plan = Plan(
            goal=query,
            needs_retrieval=bool(profile.get("needs_retrieval")),
            steps=_synthetic_steps(retrieved=bool(documents)),
        )
        logger.info(
            "轻量回答完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "answer",
                "event": "answer_completed",
                "status": "ok",
                "mode": mode,
            },
        )
        return {
            "plan": plan,
            "retrieved_documents": documents,
            "final_answer": final_answer,
            "draft": final_answer,
            "sections": [],
            "outline": [],
            "validation_result": None,
            "current_step": "answer",
            "task_status": "completed",
            "is_complete": True,
            "messages": [ChatMessage(role="assistant", content=f"[answer] {summary}")],
            "step_results": step_results,
        }

    return answer_node


def _build_messages(
    state: AgentState,
    *,
    mode: str,
    target_chars: int,
    documents: list[RetrievedDocument],
    compact: bool = False,
) -> list[ChatMessage]:
    prompt_name = "answer_brief.md" if mode == "brief" else "answer_direct.md"
    system_prompt = render_prompt(prompt_name, target_chars=target_chars)
    parts = [f"用户任务：{state.get('user_query', '')}"]
    rendered = render_preferences(state)
    if rendered:
        parts.append(rendered)
    memories = render_memories(state, "answer", compact=compact)
    if memories:
        parts.append(memories)

    if documents:
        parts.append(f"检索到的资料（请用 [编号] 引用）：\n{format_context(documents)}")
    elif mode == "brief" and (state.get("task_profile") or {}).get("needs_retrieval"):
        parts.append("注意：知识库没有检索到相关资料，请只依据通用知识作答，并说明未引用用户资料。")

    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content="\n\n".join(parts)),
    ]


async def _repair_citations(
    llm: LLMProvider,
    original_messages: list[ChatMessage],
    content: str,
    *,
    documents: list[RetrievedDocument],
) -> tuple[str, bool]:
    """最多一次引用修复；失败或仍越界时保留原文并如实标注。"""
    source_count = len(dedupe_documents(documents))
    dangling = dangling_citation_indices(content, source_count=source_count)
    if not dangling:
        return content, False

    issue = citation_issue_text(dangling, source_count=source_count)
    repair_messages = [
        *original_messages,
        ChatMessage(role="assistant", content=content),
        ChatMessage(
            role="user",
            content=render_prompt("answer_repair.md", issue=issue),
        ),
    ]
    try:
        with thinking_scope(False):
            repaired = await llm.chat(repair_messages, temperature=0.0)
    except LLMError:
        return content, False

    candidate = repaired.content.strip()
    if not candidate:
        return content, False
    if dangling_citation_indices(candidate, source_count=source_count):
        return content, False
    return candidate, True


def _synthetic_steps(*, retrieved: bool) -> list[PlanStep]:
    steps: list[PlanStep] = []
    if retrieved:
        steps.append(
            PlanStep(
                id="research",
                type="retrieval",
                description="检索个人知识库",
                skill_id=None,
            )
        )
    steps.append(
        PlanStep(
            id="answer",
            type="writing",
            description="直接回答问题（不生成章节）",
            skill_id=None,
        )
    )
    return steps
