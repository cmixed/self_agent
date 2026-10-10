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
    MAX_SECTIONS,
    chapter_target,
    failed_chapters,
    is_chapter_failed,
    last_written_index,
    next_pending_index,
)
from app.agents.citations import (
    citation_issue_text,
    dangling_citation_indices,
    find_chapters_with_dangling,
)
from app.agents.summarizer import assemble_document
from app.agents.writer import chapter_char_target
from app.core.limits import DEFAULT_TOTAL_CHARS
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, Section, StepResult, ValidationResult
from app.rag.tools import dedupe_documents, format_context

logger = get_logger(__name__)

_VALIDATOR_SYSTEM_PROMPT = """你是内容校验员。请检查给定内容是否满足任务要求。

**仅在存在以下明显缺陷时**判为不通过（passed=false）：
1. 事实性错误，或内容与「检索到的资料」相矛盾；
2. 严重遗漏：未覆盖任务计划的关键要点；
3. 引用问题：[编号] 与资料不对应，或存在资料无法支撑的断言；
4. 明显的整段重复、明显跑题，或空洞到没有任何实质信息；
5. 整篇校验时：章节结构残缺、顺序明显不合理；
6. 内容被截断（在半句话或半个列表处突然结束）导致不完整。

篇幅：如果输入给出了「目标篇幅」而实际明显偏离，请在 issues 中**提示**
（例如「实际 300 字，明显少于目标 800-1300 字」），但**仅当内容因此空泛或
残缺时才判不通过**；篇幅偏差本身不触发重写。

以下情况**不应**判为不通过：措辞与文风偏好、句式重复、
可以进一步展开等非实质性改进空间。

只输出 JSON，不要输出解释文字：
{"passed": true/false, "issues": ["问题1"],
 "suggested_action": "continue|retry_writer|replan", "chapter": null 或 章节号}

suggested_action 取值含义：
- continue：内容合格（通过时固定用 continue）；
- retry_writer：局部实质问题，重写相关章节即可；
- replan：计划本身方向或拆分有问题，需要重新规划。

"chapter" 用法（**整篇校验时尤其重要**）：
- 问题能定位到某一章 → 填写该章的序号（从 1 开始）并把 suggested_action 设为
  retry_writer：系统只会重写这一章，代价远小于重新规划；
- 只有计划/结构本身有问题（整体跑题、章节划分不合理、顺序错误）才用 replan；
- 无法定位到具体章节时填 null。
"""


class ValidationModel(BaseModel):
    """Validator 的结构化输出。"""

    passed: bool
    issues: list[str] = Field(default_factory=list, max_length=8)
    suggested_action: Literal["continue", "retry_writer", "replan"] = "continue"
    # 整篇校验时：问题可定位到的章节序号（1 基）。越界/缺失一律忽略（见 _resolve_action）
    chapter: int | None = None


def resolve_scope(
    state: AgentState, *, max_retries: int, max_sections: int = MAX_SECTIONS
) -> tuple[str, int | None]:
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
    # 已达重试上限的章节按「⚠️ 记录后放行」处理：继续重校验它只会
    # 在 validator 之间空转直到触发递归上限（该章内容不会因为再看一遍而变化）
    chapter_exhausted = is_chapter_failed(state, current, max_retries=max_retries)
    pending = next_pending_index(
        state, max_retries=max_retries, max_sections=max_sections
    )

    if pending is not None or (not chapter_done and not chapter_exhausted):
        return "chapter", current
    return "document", None


def _render_input(
    state: AgentState,
    *,
    scope: str,
    target: str,
    content: str,
    char_target: tuple[int, int] | None = None,
) -> str:
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
    if char_target is not None:
        low, high = char_target
        lines.append(f"目标篇幅（本章）：约 {low}-{high} 字；当前实际 {len(content)} 字")
    lines.append(f"待校验内容（{label}）：\n{content}")
    return "\n".join(lines)


def _render_chapter(sections: list[Section], index: int) -> str:
    if index < 0 or index >= len(sections):
        return ""
    section = sections[index]
    return f"## {section.get('title', '')}\n\n{section.get('content', '')}"


def _resolve_action_and_target(
    model: ValidationModel,
    *,
    scope: str,
    target: str,
    total_sections: int,
    state: AgentState,
    max_retries: int,
) -> tuple[str, str]:
    """把模型判定归一化为 ``(action, target)``。

    整篇校验的 ``retry_writer`` 原先一律升级为 ``replan``（全文重写），代价过大：
    只要能定位到具体章节，就改成**章级重写**；只有确实定位不到（计划/结构问题）
    才升级为 replan。章节序号非法（缺失/越界）时按原规则处理，模型输出不会破坏流程。

    **定位到的章节若已耗尽重试**：重写不会发生，此时必须降级为「整篇报告后收尾」
    （``action=continue`` 且 ``target=document``）。否则结果里的 target 是 ``chapter_N``，
    路由无法区分「章级判决」与「整篇判决定位到章」，会再次回到 validator，
    形成 validator↔validator 空转直到递归上限（真实本地模型上已复现）。
    """
    if model.passed:
        return "continue", target
    if model.suggested_action == "continue":
        # 模型自相矛盾（未通过却说 continue）时按重写处理，避免空转
        return "retry_writer", target
    if scope == "document" and model.suggested_action == "retry_writer":
        chapter = model.chapter
        if chapter is not None and 1 <= chapter <= total_sections:
            index = chapter - 1
            if is_chapter_failed(state, index, max_retries=max_retries):
                return "continue", "document"
            return "retry_writer", chapter_target(index)
        return "replan", target
    return model.suggested_action, target


def _citation_precheck(
    state: AgentState, *, scope: str, index: int | None, max_retries: int
) -> tuple[str | None, list[str]]:
    """确定性预检查：引用编号是否越界；返回 (问题章节 target, issues)。

    章级 → 直接检查该章；整篇 → 定位到第一个有问题的章节（这样后续路由是
    章级重写，而不是无法定位的整篇问题被升级成 replan）。

    **已达重试上限的章节不再参与**：预检查只是"要求重写"的依据，而对耗尽的
    章节重写已经不会再发生。若不过滤，整篇校验会反复定位回同一章
    （target 仍是 chapter_N → 路由回 validator），在 validator 之间空转到
    触发递归上限，而不是按 §16「重试耗尽后只报告」收尾。这些章节的最终状态
    仍由 ``failed_chapters`` 汇总进结果与正文 ⚠️ 标记。
    """
    source_count = len(dedupe_documents(state.get("retrieved_documents") or []))
    sections = state.get("sections") or []
    spent = {
        chapter_target(item)
        for item in failed_chapters(state, max_retries=max_retries, max_sections=MAX_SECTIONS)
    }

    if scope == "chapter" and index is not None:
        content = str(sections[index].get("content") or "") if index < len(sections) else ""
        dangling = dangling_citation_indices(content, source_count=source_count)
        if dangling and chapter_target(index) not in spent:
            return chapter_target(index), [citation_issue_text(dangling, source_count=source_count)]
        return None, []

    offenders = [
        item
        for item in find_chapters_with_dangling(sections, source_count=source_count)
        if chapter_target(item) not in spent
    ]
    if offenders:
        index = offenders[0]
        dangling = dangling_citation_indices(
            str(sections[index].get("content") or ""), source_count=source_count
        )
        return chapter_target(index), [citation_issue_text(dangling, source_count=source_count)]
    return None, []


def _build_update(
    state: AgentState,
    *,
    result: ValidationResult,
    max_retries: int,
    origin: str,
) -> dict:
    """把校验结论落成 state 更新（计数、预算、摘要、消息），两条路径共用。"""
    target = result["target"]
    passed = bool(result["passed"])
    action = result["suggested_action"]

    retry_counts = dict(state.get("retry_counts") or {})
    replan_count = state.get("retry_count", 0)
    if not passed:
        if action == "replan":
            replan_count += 1
        else:
            retry_counts[target] = retry_counts.get(target, 0) + 1
    chapter_validations = {**(state.get("chapter_validations") or {}), target: result}
    exhausted = (
        not passed and action != "replan" and retry_counts.get(target, 0) >= max_retries
    )

    if passed:
        summary = f"校验通过（{target}）"
    else:
        reason = "；".join(result["issues"]) or action
        summary = f"校验未通过（{target}）：{reason}"
        if exhausted:
            summary = f"{summary}；该章节已达重试上限，跳过并继续其他章节"
    if origin == "citation":
        summary = f"[引用编号检查] {summary}"
    elif origin == "located":
        summary = f"[整篇校验定位到 {target}] {summary}"

    logger.info(
        "validator 完成",
        extra={
            "task_id": state.get("task_id"),
            "node": "validator",
            "event": "validator_completed",
            "status": "ok" if passed else "failed",
            "origin": origin,
        },
    )
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
                status="ok" if passed else "error",
                summary=summary,
            )
        ],
    }


def make_validator_node(
    llm: LLMProvider,
    *,
    max_retries: int = 2,
    max_sections: int = MAX_SECTIONS,
    target_total_chars: int = DEFAULT_TOTAL_CHARS,
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造 validator 节点。"""

    async def validator_node(state: AgentState) -> dict:
        scope, index = resolve_scope(
            state, max_retries=max_retries, max_sections=max_sections
        )
        sections = state.get("sections") or []

        # --- 确定性预检查：引用编号越界 → 章级重试，不调用 LLM、不触发 replan ---
        citation_target, citation_issues = _citation_precheck(
        state, scope=scope, index=index, max_retries=max_retries
    )
        if citation_target is not None:
            return _build_update(
                state,
                result=ValidationResult(
                    passed=False,
                    issues=citation_issues,
                    suggested_action="retry_writer",  # type: ignore[typeddict-item]
                    target=citation_target,
                ),
                max_retries=max_retries,
                origin="citation",
            )

        if scope == "chapter" and index is not None:
            target = chapter_target(index)
            content = _render_chapter(sections, index)
        else:
            target = "document"
            content = assemble_document(state, max_retries=max_retries)

        char_target = None
        if scope == "chapter":
            char_target = chapter_char_target(target_total_chars, len(state.get("outline") or []))
        messages = [
            ChatMessage(role="system", content=_VALIDATOR_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=_render_input(
                    state, scope=scope, target=target, content=content, char_target=char_target
                ),
            ),
        ]
        model = await llm.chat_structured(
            messages, ValidationModel, temperature=0.0, max_retries=max_retries
        )
        action, resolved_target = _resolve_action_and_target(
            model,
            scope=scope,
            target=target,
            total_sections=len(state.get("outline") or []),
            state=state,
            max_retries=max_retries,
        )
        located = scope == "document" and resolved_target != target

        result = ValidationResult(
            passed=model.passed,
            issues=list(model.issues),
            suggested_action=action,  # type: ignore[typeddict-item]
            target=resolved_target,
        )
        return _build_update(
            state,
            result=result,
            max_retries=max_retries,
            origin="located" if located else "llm",
        )

    return validator_node


def make_route_after_validation(*, max_retries: int, max_sections: int = MAX_SECTIONS):
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
        pending = next_pending_index(
            state, max_retries=max_retries, max_sections=max_sections
        )

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
