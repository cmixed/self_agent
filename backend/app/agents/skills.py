"""技能节点。

技能是 Agent 可调用的结构化指令模块（见 ``app/services/skill_service.py``）。
Planner 可在计划中加入 ``type="skill"`` 的步骤；本节点每次执行计划中**第一个
尚未完成**的技能步骤，循环路由直到耗尽（与 writer 按章节循环同一惯用法）。

技能产出（SkillOutput）追加进 State，供 outline / writer 作为上下文使用。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import NotRequired, TypedDict

from app.core.limits import (
    DEFAULT_TOTAL_CHARS,
    MAX_SKILL_CONTEXT_CHARS,
    SKILL_HARD_MAX_CHARS,
    SKILL_TARGET_MAX_CHARS,
    SKILL_TARGET_MIN_CHARS,
)
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, PlanStep, SkillOutput, StepResult
from app.prompts import render_prompt
from app.rag.tools import format_context

logger = get_logger(__name__)

# 单个计划中允许的技能步骤上限（防滥用，与 MAX_SECTIONS 同类的安全约束）
MAX_SKILL_STEPS = 2

# L3：最多加载一个附件、最多追加一次模型调用（协议固定，不做递归）
MAX_RESOURCE_LOADS = 1
_RESOURCE_REQUEST_RE = re.compile(r"\[\[NEED_RESOURCE:\s*([^\]\n]+?)\s*\]\]")


class SkillMeta(TypedDict):
    """L1 技能目录：Planner 只需要判断「有哪些技能、何时用」。"""

    skill_id: str
    name: str
    description: str


class SkillResource(TypedDict):
    """技能附件：目录只给 name，content 仅在模型请求时注入。"""

    name: str
    content: str


class CatalogEntry(SkillMeta):
    """L2 技能定义：实际执行时才按 skill_id 读取正文。"""

    content: str
    resources: NotRequired[list[SkillResource]]


@dataclass(frozen=True)
class SkillCatalog:
    """技能目录快照。

    Planner 只看 :attr:`metadata`（id/name/description）；正文只在 skills 节点
    ``get(skill_id)`` 命中后读取，避免把整库技能正文塞进每次规划请求。
    """

    _definitions: Mapping[str, CatalogEntry]

    @classmethod
    def from_entries(cls, entries: Sequence[CatalogEntry] | SkillCatalog | None) -> SkillCatalog:
        if isinstance(entries, SkillCatalog):
            return entries
        return cls({entry["skill_id"]: entry for entry in entries or []})

    @property
    def metadata(self) -> list[SkillMeta]:
        return [
            SkillMeta(
                skill_id=entry["skill_id"],
                name=entry["name"],
                description=entry["description"],
            )
            for entry in self._definitions.values()
        ]

    def get(self, skill_id: str) -> CatalogEntry | None:
        return self._definitions.get(skill_id)

    def __bool__(self) -> bool:
        return bool(self._definitions)


def pending_skill_step(state: AgentState) -> PlanStep | None:
    """返回计划中第一个尚未执行的技能步骤；无则 None。"""
    plan = state.get("plan")
    if not plan:
        return None
    done = {output.get("skill_id") for output in state.get("skill_outputs") or []}
    for step in plan.get("steps", []):
        if step.get("type") == "skill" and step.get("skill_id") not in done:
            return step
    return None


def make_route_after_skills() -> Callable[[AgentState], str]:
    """技能节点后的路由：还有未执行的技能步骤 → skills，否则 → outline。"""

    def route_after_skills(state: AgentState) -> str:
        if pending_skill_step(state) is not None:
            return "skills"
        return "outline"

    return route_after_skills


def _resource_directory(resources: Sequence[SkillResource]) -> str:
    """L3 附件目录：只列名字，不泄露正文。"""
    if not resources:
        return ""
    names = "\n".join(f"- {resource['name']}" for resource in resources)
    return render_prompt("skill_resource_directory.md", resources=names).strip()


def _requested_resource(content: str) -> str | None:
    match = _RESOURCE_REQUEST_RE.search(content)
    return match.group(1).strip() if match else None


def _strip_resource_requests(content: str) -> str:
    """移除协议标记：最终输出与后续上下文都不应包含内部指令。"""
    return _RESOURCE_REQUEST_RE.sub("", content).strip()


def skill_output_target_chars(state: AgentState) -> int:
    """技能结论的软目标：约为最终长文目标的 1/3，并有上下限。

    技能产出是写作依据而不是最终文章；目标随任务篇幅增长，但不会无限放大。
    """
    profile = state.get("task_profile") or {}
    try:
        total = int(profile.get("target_chars") or DEFAULT_TOTAL_CHARS)
    except (TypeError, ValueError):
        total = DEFAULT_TOTAL_CHARS
    return max(SKILL_TARGET_MIN_CHARS, min(SKILL_TARGET_MAX_CHARS, total // 3))


def clip_skill_content(content: str) -> tuple[str, bool]:
    """技能输出的最后安全网：超过硬上限时在句/段边界截断，并留下可见说明。

    正常路径靠提示词软目标控制；这里只处理模型异常膨胀，避免污染后续上下文。
    """
    if len(content) <= SKILL_HARD_MAX_CHARS:
        return content, False

    window = content[:SKILL_HARD_MAX_CHARS]
    cut = max(window.rfind("\n"), window.rfind("。"), window.rfind("；"))
    if cut >= int(SKILL_HARD_MAX_CHARS * 0.8):
        window = window[: cut + 1]
    note = "\n\n（技能输出超过安全上限，已截断；请缩小任务范围以获得完整结论。）"
    return window.rstrip() + note, True


def render_skill_outputs(state: AgentState, *, max_chars: int = MAX_SKILL_CONTEXT_CHARS) -> str:
    """把已完成技能的结论渲染为上下文块（供 outline / writer 拼接）。"""
    outputs = state.get("skill_outputs") or []
    if not outputs:
        return ""
    blocks = [
        f"### 技能「{output.get('skill_name', '')}」结论\n{output.get('content', '')}"
        for output in outputs
    ]
    rendered = "\n\n".join(blocks)
    if max_chars > 0 and len(rendered) > max_chars:
        rendered = rendered[:max_chars].rstrip()
        rendered += "\n\n（技能结论较长，以上为节选；未展开部分不作为写作依据。）"
    return rendered


def skill_catalog_for_prompt(catalog: Sequence[SkillMeta]) -> str:
    """渲染给 Planner 的技能目录说明（只含 L1 元数据）。"""
    lines = ["可用技能（type 必须为 skill，且必须填写对应的 skill_id）："]
    for entry in catalog:
        lines.append(
            f'- skill_id="{entry["skill_id"]}" 名称：{entry["name"]}（{entry["description"]}）'
        )
    lines.append(f"最多选择 {MAX_SKILL_STEPS} 个技能步骤；没有合适的技能就不要添加 skill 步骤。")
    return "\n".join(lines)


def make_skills_node(
    llm: LLMProvider, catalog: Sequence[CatalogEntry] | SkillCatalog
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造绑定了 LLM 与技能目录的 skills 节点。

    正文按 ``skill_id`` 在执行时读取（L2）：未选中的技能不会出现在提示词中。
    """

    skill_catalog = SkillCatalog.from_entries(catalog)

    async def skills_node(state: AgentState) -> dict:
        step = pending_skill_step(state)
        if step is None:
            # 路由兜底（正常情况下路由函数已保证不会空跑）
            return {}

        skill_id = str(step.get("skill_id") or "")
        definition = skill_catalog.get(skill_id)
        if definition is None:
            logger.warning(
                "计划引用了不存在的技能，跳过该步骤",
                extra={"task_id": state.get("task_id"), "node": "skills", "skill_id": skill_id},
            )
            return {
                "current_step": step.get("id"),
                "step_results": [
                    StepResult(
                        step_id=str(step.get("id", "")),
                        status="error",
                        summary="技能不存在，已跳过",
                    )
                ],
            }

        context_parts = [
            f"任务目标：{(state.get('plan') or {}).get('goal', '')}",
            f"用户任务：{state.get('user_query', '')}",
        ]
        documents = state.get("retrieved_documents") or []
        if documents:
            context_parts.append("参考资料：\n" + format_context(documents))
        resources = definition.get("resources") or []
        directory = _resource_directory(resources)
        if directory:
            context_parts.append(directory)
        target_chars = skill_output_target_chars(state)
        context_parts.append(render_prompt("skill_execute.md", target_chars=target_chars).strip())
        context_parts.append(
            "输出要求：**不要使用 [编号] 形式标注引用**——[编号] 由正文统一按"
            "「检索到的资料」顺序生成；如需指明依据，请直接写文件名或章节名。"
        )

        messages = [
            # L2：技能正文只放在 system；user 里不再重复，省一半技能 token
            ChatMessage(role="system", content=definition["content"]),
            ChatMessage(role="user", content="\n\n".join(context_parts)),
        ]
        response = await llm.chat(messages, temperature=0.3)
        raw = response.content.strip()
        content = _strip_resource_requests(raw)
        resource_used = ""
        truncated = response.finish_reason == "length"
        extra_call_made = False

        # L3：最多加载一个附件、最多追加一次调用；后续再请求也不递归。
        # 这次追加调用与「截断续写」共用同一个额外调用预算（二者最多一个）。
        requested = _requested_resource(raw)
        if requested and MAX_RESOURCE_LOADS > 0:
            resource = next(
                (item for item in resources if item["name"] == requested),
                None,
            )
            if resource is None:
                logger.warning(
                    "技能请求了不存在的附件，已忽略",
                    extra={
                        "task_id": state.get("task_id"),
                        "node": "skills",
                        "skill_id": skill_id,
                        "resource": requested,
                    },
                )
            else:
                followup = await llm.chat(
                    [
                        *messages,
                        ChatMessage(role="assistant", content=content or "（需要附件）"),
                        ChatMessage(
                            role="user",
                            content=render_prompt(
                                "skill_resource_followup.md",
                                name=resource["name"],
                                content=resource["content"],
                            ),
                        ),
                    ],
                    temperature=0.3,
                )
                extra_call_made = True
                if followup.content.strip():
                    content = _strip_resource_requests(followup.content.strip())
                    truncated = followup.finish_reason == "length"
                else:
                    truncated = True
                resource_used = resource["name"]

        # 输出被长度上限截断：追加一次有限续写（最多一次，绝不无限续）。
        if truncated and not extra_call_made and content:
            continuation = await llm.chat(
                [
                    *messages,
                    ChatMessage(role="assistant", content=content),
                    ChatMessage(
                        role="user",
                        content=render_prompt(
                            "skill_continue.md",
                            tail=content[-500:],
                            target_chars=target_chars,
                        ),
                    ),
                ],
                temperature=0.3,
            )
            if continuation.content.strip():
                content = f"{content}\n{_strip_resource_requests(continuation.content.strip())}"
                truncated = continuation.finish_reason == "length"
            else:
                truncated = True
            logger.warning(
                "技能输出被长度上限截断，已尝试一次续写",
                extra={
                    "task_id": state.get("task_id"),
                    "node": "skills",
                    "event": "skill_truncated",
                    "status": "warning",
                    "skill_id": skill_id,
                    "still_truncated": truncated,
                },
            )

        content, clipped = clip_skill_content(content)
        truncated = truncated or clipped

        summary = content.splitlines()[0][:120] if content else "（无输出）"
        if resource_used:
            summary = f"已加载附件「{resource_used}」；{summary}"
        if truncated:
            summary += "（输出被截断，内容可能不完整）"

        logger.info(
            "技能执行完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "skills",
                "event": "skill_completed",
                "status": "ok" if not truncated else "warning",
                "skill_id": skill_id,
                "target_chars": target_chars,
                "truncated": truncated,
            },
        )
        output: SkillOutput = SkillOutput(
            skill_id=skill_id,
            skill_name=definition["name"],
            step_id=str(step.get("id", "")),
            summary=summary,
            content=content,
        )
        return {
            "skill_outputs": [output],
            "current_step": step.get("id"),
            "task_status": "writing",
            "step_results": [
                StepResult(
                    step_id=str(step.get("id", "")),
                    status="ok" if not truncated else "error",
                    summary=(
                        f"技能「{definition['name']}」执行完成"
                        + (f"（按需附件：{resource_used}）" if resource_used else "")
                        + ("（输出被截断）" if truncated else "")
                    ),
                )
            ],
            "messages": [
                ChatMessage(
                    role="assistant",
                    content=f"[skills] 技能「{definition['name']}」执行完成",
                )
            ],
        }

    return skills_node
