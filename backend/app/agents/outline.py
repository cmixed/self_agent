"""Outline 节点：生成长文大纲。

Phase 4A：长文采用「大纲 → 分章节生成 → 汇总」的方式，避免一次性生成整篇
（AGENTS.md §15）。大纲标题写入 ``AgentState.outline``，供逐章写作与 Validator
校验结构使用。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from app.agents.preferences import render_preferences
from app.core.limits import (
    DEFAULT_MAX_SECTIONS,
    DEFAULT_TARGET_SECTIONS,
    MIN_SECTIONS,
    SCHEMA_SECTION_GUARD,
)
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, Section, StepResult

logger = get_logger(__name__)


def _outline_system_prompt(target_sections: int) -> str:
    """提示词中的章节上限与配置同源（避免提示词与上限各写各的）。"""
    return f"""你是一个写作大纲设计者。请为用户的写作任务设计章节大纲。

要求：
1. 只输出 JSON，不要输出解释文字或 Markdown 代码块。
2. JSON 结构必须为：{{"sections": [{{"title": "章节标题"}}]}}
3. 章节数量由任务实际需要决定，**不要为了凑数而拆分**：
   - 内容适合单篇、篇幅不长 → 只给 1 章（表示整篇不划分章节）；
   - 中等篇幅 → 2-4 章；
   - 复杂长文 → 最多 {target_sections} 章。
   所有情况至少要有 1 章，标题要能概括该部分主题。
4. 如果提供了参考资料，请让大纲覆盖资料中的关键要点。
"""


class OutlineSectionModel(BaseModel):
    title: str = Field(min_length=1)


class OutlineModel(BaseModel):
    # 结构防爆上限远高于生成上限：模型多给几章时截断并说明，而不是校验失败
    sections: list[OutlineSectionModel] = Field(min_length=1, max_length=SCHEMA_SECTION_GUARD)


def _render_outline_input(state: AgentState, documents_context: str) -> str:
    plan = state.get("plan")
    lines = [f"用户任务：{state.get('user_query', '')}"]
    if plan:
        lines.append(f"任务目标：{plan.get('goal', '')}")
    if documents_context:
        lines.append(f"参考资料：\n{documents_context}")
    rendered = render_preferences(state)
    if rendered:
        lines.append(rendered)
    return "\n".join(lines)


def make_outline_node(
    llm: LLMProvider,
    *,
    max_retries: int = 2,
    target_sections: int = DEFAULT_TARGET_SECTIONS,
    max_sections: int = DEFAULT_MAX_SECTIONS,
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造 outline 节点。

    ``target_sections`` 是提示词里的**参考上限**（不是强制章节数），
    ``max_sections`` 是实际生成上限：模型给出更多章节时按上限截断，
    并把截断事实写入 step_result 与消息（可见，不静默）。
    """
    target = max(MIN_SECTIONS, min(target_sections, max_sections))

    async def outline_node(state: AgentState) -> dict:
        from app.agents.skills import render_skill_outputs
        from app.rag.tools import format_context

        context_parts: list[str] = []
        documents_context = format_context(state.get("retrieved_documents") or [])
        if documents_context:
            context_parts.append(documents_context)
        skill_context = render_skill_outputs(state)
        if skill_context:
            context_parts.append(f"已完成的技能分析结论：\n{skill_context}")
        context = "\n\n".join(context_parts)
        messages = [
            ChatMessage(role="system", content=_outline_system_prompt(target)),
            ChatMessage(role="user", content=_render_outline_input(state, context)),
        ]
        outline_model = await llm.chat_structured(
            messages, OutlineModel, temperature=0.2, max_retries=max_retries
        )

        proposed = [Section(title=section.title, content="") for section in outline_model.sections]
        outline = proposed[:max_sections]
        truncated_from = len(proposed) if len(proposed) > max_sections else None
        if truncated_from is not None:
            logger.warning(
                "大纲章节数超出上限，已截断",
                extra={
                    "task_id": state.get("task_id"),
                    "node": "outline",
                    "event": "outline_truncated",
                    "status": "warning",
                    "proposed_sections": truncated_from,
                    "max_sections": max_sections,
                },
            )
        titles = [section["title"] for section in outline]
        # sections 与 outline 按下标对齐，供逐章填充 / 重写 / 跳过失败章节
        sections = [Section(title=title, content="") for title in titles]

        logger.info(
            "outline 完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "outline",
                "event": "outline_completed",
                "status": "ok",
            },
        )
        summary = f"生成 {len(outline)} 个章节"
        if truncated_from is not None:
            summary += f"（模型给出 {truncated_from} 章，已按上限 {max_sections} 截断）"

        return {
            "outline": outline,
            # replan 时重置生成与校验状态，确保从干净状态重新写作
            "sections": sections,
            "validation_result": None,
            "retry_counts": {},
            "chapter_validations": {},
            "current_step": "outline",
            "task_status": "writing",
            "messages": [
                ChatMessage(
                    role="assistant",
                    content=f"[outline] {summary}：{'、'.join(titles)}",
                )
            ],
            "step_results": [StepResult(step_id="outline", status="ok", summary=summary)],
        }

    return outline_node
