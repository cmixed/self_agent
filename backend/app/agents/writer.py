"""Writer 节点：逐章撰写正文。

Phase 4A：每次调用只写一章，由 Graph 循环驱动直到大纲全部写完（见 AGENTS.md §15）。
这样每次 LLM 调用上下文更小、失败影响面更小，也便于展示「正在撰写第 N 章」。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.agents.outline import MAX_SECTIONS
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, Section, StepResult
from app.rag.tools import format_context

logger = get_logger(__name__)

_WRITER_SYSTEM_PROMPT = """你是一个中文写作助手。请撰写指定章节的正文。

要求：
1. 只输出该章节的正文，不要重复章节标题，也不要输出「参考来源」列表。
2. 章节内部的小标题必须使用 ### 或更深层级（###/####）；严禁使用 # 或 ##，
   因为章节标题由系统以 ## 层级统一生成。
3. 如果提供了「检索到的资料」，请优先依据资料作答，并用 [编号] 标注引用，
   例如：RAG 通过向量检索增强生成能力[1]。
4. 如果未提供资料，请只依据通用知识作答，并说明未引用用户资料。
"""


def _render_section_input(state: AgentState, *, title: str, index: int, total: int) -> str:
    plan = state.get("plan")
    lines = [f"用户任务：{state.get('user_query', '')}"]
    if plan:
        lines.append(f"任务目标：{plan.get('goal', '')}")
    lines.append(f"当前章节（第 {index}/{total} 章）：{title}")

    documents = state.get("retrieved_documents") or []
    if documents:
        lines.append(f"检索到的资料（请用 [编号] 引用）：\n{format_context(documents)}")
    elif plan and plan.get("needs_retrieval"):
        lines.append(
            "注意：本任务需要检索用户资料，但知识库中没有检索到相关内容。"
            "请只依据通用知识作答，并明确说明未引用用户资料。"
        )

    preferences = state.get("user_preferences") or {}
    if preferences:
        rendered = "；".join(f"{key}={value}" for key, value in preferences.items())
        lines.append(f"用户偏好：{rendered}")
    return "\n".join(lines)


def make_writer_node(llm: LLMProvider) -> Callable[[AgentState], Awaitable[dict]]:
    """构造 writer 节点（每次撰写一章）。"""

    async def writer_node(state: AgentState) -> dict:
        outline = state.get("outline") or []
        written = state.get("sections") or []
        index = len(written)

        if index >= len(outline):
            # 大纲已写完（正常情况下路由不会再调用本节点）
            return {}

        section = outline[index]
        title = section["title"]
        chapter = index + 1
        total = len(outline)

        messages = [
            ChatMessage(role="system", content=_WRITER_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=_render_section_input(state, title=title, index=chapter, total=total),
            ),
        ]
        response = await llm.chat(messages, temperature=0.7)

        logger.info(
            "writer 完成章节",
            extra={
                "task_id": state.get("task_id"),
                "node": "writer",
                "event": "writer_completed",
                "status": "ok",
            },
        )
        return {
            "sections": [
                Section(title=title, content=response.content.strip()),
            ],
            "current_step": f"chapter_{chapter}",
            "task_status": "writing",
            "messages": [
                ChatMessage(role="assistant", content=f"[writer] 已完成第 {chapter} 章：{title}")
            ],
            "step_results": [
                StepResult(
                    step_id=f"chapter_{chapter}",
                    status="ok",
                    summary=f"已撰写：{title}",
                )
            ],
        }

    return writer_node


def route_after_writer(state: AgentState) -> str:
    """还有章节未写则继续写，否则进入汇总。

    同时受 ``MAX_SECTIONS`` 硬上限保护，杜绝无限循环（§27）。
    """
    outline = state.get("outline") or []
    written = state.get("sections") or []
    if len(written) < len(outline) and len(written) < MAX_SECTIONS:
        return "writer"
    return "summarize"
