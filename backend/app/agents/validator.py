"""Validator 节点。

不是重新生成文章，而是检查内容质量（AGENTS.md §16）：

- **章节级**：校验刚写好的那一章；
- **整篇**：所有章节写完后，再校验整篇文档。

重试预算按**章节独立**计（``retry_counts``），每个章节最多失败 ``MAX_RETRIES`` 次：

- 未达上限：重写该章（``retry_writer``）；
- 已达上限：记录失败原因并**跳过该章**，其余章节继续执行；
- replan 是计划级操作，用全局 ``retry_count`` 单独限次。

任何路径都不会无限循环（§27）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.chapters import (
    chapter_target,
    last_written_index,
    next_pending_index,
)
from app.agents.summarizer import assemble_document
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, Section, StepResult, ValidationResult
from app.rag.tools import format_context

logger = get_logger(__name__)

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


def resolve_scope(state: AgentState, *, max_retries: int) -> tuple[str, int | None]:
    """判断本次校验的范围。

    返回 ``("chapter", index)`` 或 ``("document", None)``。
    """
    outline = state.get("outline") or []
    if not outline:
        return "document", None

    current = last_written_index(state.get("sections") or [])
    if current is None:
        return "document", None

    validations = state.get("chapter_validations") or {}
    latest = validations.get(chapter_target(current))
    chapter_done = isinstance(latest, dict) and bool(latest.get("passed"))
    pending = next_pending_index(state, max_retries=max_retries)

    if pending is not None or not chapter_done:
        return "chapter", current
    return "document", None


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

    label = "整篇文档" if scope == "document" else f"章节（{target}）"
    lines.append(f"待校验内容（{label}）：\n{content}")
    return "\n".join(lines)


def _render_chapter(sections: list[Section], index: int) -> str:
    if index < 0 or index >= len(sections):
        return ""
    section = sections[index]
    return f"## {section.get('title', '')}\n\n{section.get('content', '')}"


def _normalize_action(model: ValidationModel, *, scope: str) -> str:
    if model.passed:
        return "continue"
    if model.suggested_action == "continue":
        # 模型自相矛盾（未通过却说 continue）时按重写处理，避免空转
        return "retry_writer"
    if scope == "document" and model.suggested_action == "retry_writer":
        # 整篇问题无法定位到具体章节，升级为重新规划
        return "replan"
    return model.suggested_action


def make_validator_node(
    llm: LLMProvider, *, max_retries: int = 2
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造 validator 节点。"""

    async def validator_node(state: AgentState) -> dict:
        scope, index = resolve_scope(state, max_retries=max_retries)
        sections = state.get("sections") or []
        if scope == "chapter" and index is not None:
            target = chapter_target(index)
            content = _render_chapter(sections, index)
        else:
            target = "document"
            content = assemble_document(state, max_retries=max_retries)

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
        action = _normalize_action(model, scope=scope)

        result = ValidationResult(
            passed=model.passed,
            issues=list(model.issues),
            suggested_action=action,  # type: ignore[typeddict-item]
            target=target,
        )

        # 计费：章节失败计入该章的独立预算；replan 计入全局次数
        retry_counts = dict(state.get("retry_counts") or {})
        replan_count = state.get("retry_count", 0)
        if not model.passed:
            if action == "replan":
                replan_count += 1
            else:
                retry_counts[target] = retry_counts.get(target, 0) + 1
        chapter_validations = {**(state.get("chapter_validations") or {}), target: result}

        exhausted = (
            not model.passed and action != "replan" and retry_counts.get(target, 0) >= max_retries
        )

        logger.info(
            "validator 完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "validator",
                "event": "validator_completed",
                "status": "ok" if model.passed else "failed",
            },
        )
        if model.passed:
            summary = f"校验通过（{target}）"
        else:
            reason = "；".join(model.issues) or action
            summary = f"校验未通过（{target}）：{reason}"
            if exhausted:
                summary = f"{summary}；该章节已达重试上限，跳过并继续其他章节"

        return {
            "validation_result": result,
            "chapter_validations": chapter_validations,
            "retry_counts": retry_counts,
            "retry_count": replan_count,
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
    """构造 validator 之后的路由函数。

    可能的目标：``writer``（继续写 / 重写）、``planner``（replan）、
    ``validator``（进入整篇校验）、``summarize``（完成或安全结束）。
    """

    def route_after_validation(state: AgentState) -> str:
        result = state.get("validation_result") or {}
        target = str(result.get("target", ""))
        is_document = target == "document"
        retry_counts = state.get("retry_counts") or {}
        replan_count = state.get("retry_count", 0)
        pending = next_pending_index(state, max_retries=max_retries)

        if result.get("passed"):
            if is_document:
                return "summarize"
            if pending is not None:
                return "writer"
            # 章节全部完成，进入整篇校验
            return "validator"

        if result.get("suggested_action") == "replan" and replan_count < max_retries:
            return "planner"

        if not is_document and retry_counts.get(target, 0) < max_retries:
            return "writer"

        # 该章已达上限（或被跳过）：继续其他章节，否则进入整篇校验
        if pending is not None:
            return "writer"
        return "summarize" if is_document else "validator"

    return route_after_validation
