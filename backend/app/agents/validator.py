"""Validator 节点。

不是重新生成文章，而是检查内容质量（AGENTS.md §16）：

- **章节级**：还有章节未写完时，校验刚生成的那一章；
- **整篇**：全部章节写完后，校验整篇文档。

输出结构化结果 ``{passed, issues, suggested_action, target}``。失败时由路由决定
重写（retry_writer → writer）或重新规划（replan → planner），并受 ``MAX_RETRIES``
限制，超限后安全结束（进入 summarizer）。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.summarizer import assemble_document
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, Section, StepResult, ValidationResult
from app.rag.tools import format_context

logger = get_logger(__name__)

_CHAPTER_TARGET = re.compile(r"^chapter_(\d+)$")

_VALIDATOR_SYSTEM_PROMPT = """你是内容校验员。请检查给定内容是否满足任务要求。

检查要点：
1. 是否覆盖了任务计划要求、以及该章节应包含的要点；
2. 若提供了「检索到的资料」，正文的 [编号] 引用是否与资料对应，是否存在资料无法支撑的断言；
3. 是否存在明显重复、空泛或与主题无关的内容；
4. 整篇校验时，还要检查章节结构是否完整、顺序是否合理。

只输出 JSON，不要输出解释文字：
{"passed": true/false, "issues": ["问题1"], "suggested_action": "continue|retry_writer|replan"}

suggested_action 取值含义：
- continue：内容合格；
- retry_writer：局部问题，重写当前章节即可；
- replan：计划本身方向或拆分有问题，需要重新规划。
"""


class ValidationModel(BaseModel):
    """Validator 的结构化输出。"""

    passed: bool
    issues: list[str] = Field(default_factory=list, max_length=8)
    suggested_action: Literal["continue", "retry_writer", "replan"] = "continue"


def _render_input(state: AgentState, *, scope: str, target: str, content: str) -> str:
    plan = state.get("plan")
    lines = [f"用户任务：{state.get('user_query', '')}"]
    if plan:
        lines.append(f"任务目标：{plan.get('goal', '')}")
        steps = plan.get("steps") or []
        if steps:
            rendered = "\n".join(
                f"- [{step.get('type')}] {step.get('description')}" for step in steps
            )
            lines.append(f"计划步骤：\n{rendered}")

    outline = state.get("outline") or []
    if outline:
        titles = "、".join(section.get("title", "") for section in outline)
        lines.append(f"预定结构：{titles}")

    documents = state.get("retrieved_documents") or []
    if documents:
        lines.append(f"检索到的资料：\n{format_context(documents)}")

    scope_label = "整篇文档" if scope == "document" else f"章节（{target}）"
    lines.append(f"待校验内容（{scope_label}）：\n{content}")
    return "\n".join(lines)


def _render_chapter(sections: list[Section], index: int) -> str:
    if index < 0 or index >= len(sections):
        return ""
    section = sections[index]
    return f"## {section.get('title', '')}\n\n{section.get('content', '')}"


def resolve_target(state: AgentState) -> tuple[str, str]:
    """返回 (target, content)：``target`` 为 ``document`` 或 ``chapter_N``。"""
    outline = state.get("outline") or []
    sections = state.get("sections") or []
    if len(sections) < len(outline):
        index = len(sections) - 1
        return f"chapter_{index + 1}", _render_chapter(sections, index)
    return "document", assemble_document(state)


def make_validator_node(
    llm: LLMProvider, *, max_retries: int = 2
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造 validator 节点。"""

    async def validator_node(state: AgentState) -> dict:
        target, content = resolve_target(state)
        scope = "document" if target == "document" else "chapter"

        messages = [
            ChatMessage(role="system", content=_VALIDATOR_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=_render_input(state, scope=scope, target=target, content=content),
            ),
        ]
        model = await llm.chat_structured(
            messages, ValidationModel, temperature=0.0, max_retries=max_retries
        )

        if model.passed:
            action = "continue"
        elif model.suggested_action == "continue":
            # 模型自相矛盾（未通过却说 continue）时按重写处理，避免空转
            action = "retry_writer"
        else:
            action = model.suggested_action

        result = ValidationResult(
            passed=model.passed,
            issues=list(model.issues),
            suggested_action=action,
            target=target,
        )
        retry_count = state.get("retry_count", 0) + (0 if model.passed else 1)

        logger.info(
            "validator 完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "validator",
                "event": "validator_completed",
                "status": "ok" if model.passed else "failed",
            },
        )
        summary = (
            f"校验通过（{target}）"
            if model.passed
            else f"校验未通过（{target}）：{'；'.join(model.issues) or action}"
        )
        return {
            "validation_result": result,
            "retry_count": retry_count,
            "task_status": "validating",
            "current_step": f"validate_{target}",
            "messages": [ChatMessage(role="assistant", content=f"[validator] {summary}")],
            "step_results": [
                StepResult(
                    step_id=f"validate_{target}",
                    status="ok" if model.passed else "error",
                    summary=summary,
                )
            ],
        }

    return validator_node


def make_route_after_validation(*, max_retries: int):
    """构造 validator 之后的路由函数。"""

    def route_after_validation(state: AgentState) -> str:
        result = state.get("validation_result") or {}
        outline = state.get("outline") or []
        sections = state.get("sections") or []
        retry_count = state.get("retry_count", 0)

        if result.get("passed"):
            # 通过：还有章节就继续写，否则汇总
            return "writer" if len(sections) < len(outline) else "summarize"

        # 未通过：超过重试上限则安全结束（§16）
        if retry_count >= max_retries:
            return "summarize"

        if result.get("suggested_action") == "replan":
            return "planner"
        return "writer"

    return route_after_validation


def chapter_index_from_target(target: str) -> int | None:
    """``"chapter_2"`` -> ``1``（0 基下标）；``"document"`` -> ``None``。"""
    match = _CHAPTER_TARGET.match(target or "")
    return int(match.group(1)) - 1 if match else None
