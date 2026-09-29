"""Outline 节点：生成长文大纲。

Phase 4A：长文采用「大纲 → 分章节生成 → 汇总」的方式，避免一次性生成整篇
（AGENTS.md §15）。大纲标题写入 ``AgentState.outline``，供逐章写作与 Validator
校验结构使用。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, Section, StepResult

logger = get_logger(__name__)

# 章节数硬上限：防止异常情况下无界循环（§27 禁止无限 Loop）
MAX_SECTIONS = 8

_OUTLINE_SYSTEM_PROMPT = """你是一个写作大纲设计者。请为用户的写作任务设计章节大纲。

要求：
1. 只输出 JSON，不要输出解释文字或 Markdown 代码块。
2. JSON 结构必须为：{"sections": [{"title": "章节标题"}]}
3. 章节数量控制在 3-6 个，按逻辑顺序排列，标题简洁明确。
4. 如果提供了参考资料，请让大纲覆盖资料中的关键要点。
"""


class OutlineSectionModel(BaseModel):
    title: str = Field(min_length=1)


class OutlineModel(BaseModel):
    sections: list[OutlineSectionModel] = Field(min_length=1, max_length=MAX_SECTIONS)


def _render_outline_input(state: AgentState, documents_context: str) -> str:
    plan = state.get("plan")
    lines = [f"用户任务：{state.get('user_query', '')}"]
    if plan:
        lines.append(f"任务目标：{plan.get('goal', '')}")
    if documents_context:
        lines.append(f"参考资料：\n{documents_context}")
    preferences = state.get("user_preferences") or {}
    if preferences:
        rendered = "；".join(f"{key}={value}" for key, value in preferences.items())
        lines.append(f"用户偏好：{rendered}")
    return "\n".join(lines)


def make_outline_node(
    llm: LLMProvider, *, max_retries: int = 2
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造 outline 节点。"""

    async def outline_node(state: AgentState) -> dict:
        from app.rag.tools import format_context

        context = format_context(state.get("retrieved_documents") or [])
        messages = [
            ChatMessage(role="system", content=_OUTLINE_SYSTEM_PROMPT),
            ChatMessage(role="user", content=_render_outline_input(state, context)),
        ]
        outline_model = await llm.chat_structured(
            messages, OutlineModel, temperature=0.2, max_retries=max_retries
        )

        outline = [Section(title=section.title, content="") for section in outline_model.sections]
        titles = [section["title"] for section in outline]

        logger.info(
            "outline 完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "outline",
                "event": "outline_completed",
                "status": "ok",
            },
        )
        return {
            "outline": outline,
            # replan 时重置生成结果，确保从干净状态重新写作
            "sections": [],
            "validation_result": None,
            "current_step": "outline",
            "task_status": "writing",
            "messages": [
                ChatMessage(
                    role="assistant",
                    content=f"[outline] 生成 {len(outline)} 个章节：{'、'.join(titles)}",
                )
            ],
            "step_results": [
                StepResult(
                    step_id="outline",
                    status="ok",
                    summary=f"生成 {len(outline)} 个章节",
                )
            ],
        }

    return outline_node
