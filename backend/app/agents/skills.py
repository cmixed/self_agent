"""技能节点。

技能是 Agent 可调用的结构化指令模块（见 ``app/services/skill_service.py``）。
Planner 可在计划中加入 ``type="skill"`` 的步骤；本节点每次执行计划中**第一个
尚未完成**的技能步骤，循环路由直到耗尽（与 writer 按章节循环同一惯用法）。

技能产出（SkillOutput）追加进 State，供 outline / writer 作为上下文使用。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TypedDict

from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, PlanStep, SkillOutput, StepResult
from app.rag.tools import format_context

logger = get_logger(__name__)

# 单个计划中允许的技能步骤上限（防滥用，与 MAX_SECTIONS 同类的安全约束）
MAX_SKILL_STEPS = 2


class CatalogEntry(TypedDict):
    """技能目录条目（由 SkillService 把 SkillRecord 转换而来）。"""

    skill_id: str
    name: str
    description: str
    content: str


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


def render_skill_outputs(state: AgentState) -> str:
    """把已完成技能的结论渲染为上下文块（供 outline / writer 拼接）。"""
    outputs = state.get("skill_outputs") or []
    if not outputs:
        return ""
    blocks = [
        f"### 技能「{output.get('skill_name', '')}」结论\n{output.get('content', '')}"
        for output in outputs
    ]
    return "\n\n".join(blocks)


def skill_catalog_for_prompt(catalog: Sequence[CatalogEntry]) -> str:
    """渲染给 Planner 的技能目录说明。"""
    lines = ["可用技能（type 必须为 skill，且必须填写对应的 skill_id）："]
    for entry in catalog:
        lines.append(
            f'- skill_id="{entry["skill_id"]}" 名称：{entry["name"]}'
            f'（{entry["description"]}）'
        )
    lines.append(f"最多选择 {MAX_SKILL_STEPS} 个技能步骤；没有合适的技能就不要添加 skill 步骤。")
    return "\n".join(lines)


def make_skills_node(
    llm: LLMProvider, catalog: Sequence[CatalogEntry]
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造绑定了 LLM 与技能目录的 skills 节点。"""

    definitions = {entry["skill_id"]: entry for entry in catalog}

    async def skills_node(state: AgentState) -> dict:
        step = pending_skill_step(state)
        if step is None:
            # 路由兜底（正常情况下路由函数已保证不会空跑）
            return {}

        skill_id = str(step.get("skill_id") or "")
        definition = definitions.get(skill_id)
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
        context_parts.append(f"技能说明（{definition['name']}）：\n{definition['content']}")
        context_parts.append(
            "输出要求：**不要使用 [编号] 形式标注引用**——[编号] 由正文统一按"
            "「检索到的资料」顺序生成；如需指明依据，请直接写文件名或章节名。"
        )

        response = await llm.chat(
            [
                ChatMessage(role="system", content=definition["content"]),
                ChatMessage(role="user", content="\n\n".join(context_parts)),
            ],
            temperature=0.3,
        )
        content = response.content.strip()
        summary = content.splitlines()[0][:120] if content else "（无输出）"

        logger.info(
            "技能执行完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "skills",
                "event": "skill_completed",
                "status": "ok",
                "skill_id": skill_id,
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
                    status="ok",
                    summary=f"技能「{definition['name']}」执行完成",
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
