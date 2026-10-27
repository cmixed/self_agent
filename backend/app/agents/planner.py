"""Planner 节点。

职责（AGENTS.md §8）：理解任务、判断是否需要知识库检索、拆解为结构化步骤。
输出必须是结构化数据（Pydantic 校验），解析失败时有限重试。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.memory_context import render_memories
from app.agents.preferences import render_preferences
from app.agents.skills import (
    MAX_SKILL_STEPS,
    CatalogEntry,
    SkillCatalog,
    SkillMeta,
    skill_catalog_for_prompt,
)
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, Plan, PlanStep, StepResult
from app.prompts import render_prompt

logger = get_logger(__name__)

_PLANNER_SYSTEM_PROMPT = render_prompt("planner.md")


class PlanStepModel(BaseModel):
    """Planner 输出的单个步骤（用于 Schema 校验）。"""

    id: str = Field(min_length=1)
    type: Literal["retrieval", "skill", "outline", "writing", "validation"]
    description: str = Field(min_length=1)
    skill_id: str | None = None


class PlanModel(BaseModel):
    """Planner 输出的结构化计划。

    ``needs_retrieval`` 缺省为 True：本地小模型常省略该字段，
    缺失时按「需要检索」处理比整单任务失败更合适（只是多一次检索）。
    """

    goal: str = Field(min_length=1)
    needs_retrieval: bool = True
    steps: list[PlanStepModel] = Field(min_length=1)


def _render_planner_input(state: AgentState, *, compact: bool = False) -> str:
    parts = [f"用户任务：{state.get('user_query', '')}"]
    rendered = render_preferences(state)
    if rendered:
        parts.append(rendered)
    memories = render_memories(state, "planner", compact=compact)
    if memories:
        parts.append(memories)

    if state.get("retrieval_mode") == "none":
        parts.append(
            "检索限制：本次任务明确不使用知识库。needs_retrieval 必须为 false，"
            "不要生成 retrieval 步骤，也不要假定能获取任何资料。"
        )

    scope = state.get("retrieval_scope") or {}
    scope_documents = scope.get("document_ids")
    if scope_documents is not None:
        # 让规划器知道本次只能检索所选范围，避免规划出范围外资料
        label = scope.get("label") or "用户选定范围"
        parts.append(
            f"检索范围：{label}（共 {len(scope_documents)} 篇资料，"
            "只能依据该范围内的资料作答，不得假定可获取范围外内容）"
        )
    return "\n".join(parts)


def _validate_skill_steps(
    steps: list[PlanStepModel], catalog: Sequence[SkillMeta] | None
) -> list[PlanStepModel]:
    """过滤非法技能步骤：无目录时全部剔除；skill_id 不在目录中剔除；超上限截断。"""
    if not catalog:
        return [step for step in steps if step.type != "skill"]

    valid_ids = {entry["skill_id"] for entry in catalog}
    kept: list[PlanStepModel] = []
    skill_count = 0
    for step in steps:
        if step.type != "skill":
            kept.append(step)
            continue
        if step.skill_id in valid_ids and skill_count < MAX_SKILL_STEPS:
            kept.append(step)
            skill_count += 1
        else:
            logger.warning(
                "忽略非法技能步骤",
                extra={"node": "planner", "skill_id": step.skill_id, "event": "skill_step_dropped"},
            )
    return kept


def make_planner_node(
    llm: LLMProvider,
    *,
    max_retries: int = 2,
    skill_catalog: Sequence[CatalogEntry] | SkillCatalog | None = None,
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造绑定了 LLM 的 planner 节点。

    ``skill_catalog`` 非空时注入 L1 目录（id/name/description），Planner 可在
    计划中加入技能步骤；技能正文不会进入规划提示词。
    """
    catalog = SkillCatalog.from_entries(skill_catalog)
    # 本地小模型上下文更小：记忆预算减半，避免挤占 num_ctx
    compact_memory = bool(getattr(llm, "is_local", False))

    async def planner_node(state: AgentState) -> dict:
        # 技能是显式 opt-in：默认不把目录注入 planner，避免模型被引导去
        # 添加「技能步骤」而多出一次 LLM 调用（简单任务尤其明显）。
        allow_skills = bool((state.get("task_profile") or {}).get("allow_skills", True))
        catalog_meta = catalog.metadata if allow_skills else []
        system_prompt = _PLANNER_SYSTEM_PROMPT
        if catalog_meta:
            system_prompt = f"{system_prompt}\n\n{skill_catalog_for_prompt(catalog_meta)}"
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=_render_planner_input(state, compact=compact_memory)),
        ]
        plan_model = await llm.chat_structured(
            messages, PlanModel, temperature=0.0, max_retries=max_retries
        )

        steps: list[PlanStep] = [
            PlanStep(
                id=step.id,
                type=step.type,
                description=step.description,
                skill_id=step.skill_id,
            )
            for step in _validate_skill_steps(plan_model.steps, catalog_meta)
        ]
        # 「不检索」是硬约束：即使模型忽略了提示，也不允许保留检索步骤
        if state.get("retrieval_mode") == "none":
            steps = [step for step in steps if step["type"] != "retrieval"]
            if not steps:
                steps = [
                    PlanStep(
                        id="write",
                        type="writing",
                        description="根据任务要求直接生成内容（本次未使用知识库）",
                        skill_id=None,
                    )
                ]
        needs_retrieval = (
            False if state.get("retrieval_mode") == "none" else plan_model.needs_retrieval
        )
        plan: Plan = Plan(
            goal=plan_model.goal,
            needs_retrieval=needs_retrieval,
            steps=steps,
        )

        summary = f"生成 {len(steps)} 个步骤，needs_retrieval={needs_retrieval}"
        logger.info(
            "planner 完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "planner",
                "event": "planner_completed",
                "status": "ok",
            },
        )
        return {
            "plan": plan,
            "current_step": steps[0]["id"] if steps else None,
            "task_status": "writing",
            "messages": [
                ChatMessage(
                    role="assistant",
                    content=f"[planner] 目标：{plan['goal']}；共 {len(steps)} 个步骤",
                )
            ],
            "step_results": [StepResult(step_id="plan", status="ok", summary=summary)],
        }

    return planner_node


def make_route_after_planner(
    *, retrieval_available: bool, skills_available: bool = False
) -> Callable[[AgentState], str]:
    """构造 planner 之后的路由函数。

    有计划且需要检索（且检索能力可用）→ researcher；否则进入技能阶段
    （有技能目录时）或直接 → outline；无计划 → 安全结束。
    """

    next_stage = "skills" if skills_available else "outline"

    def route_after_planner(state: AgentState) -> str:
        plan = state.get("plan")
        if not plan:
            return "end"
        if state.get("retrieval_mode") == "none":
            return next_stage
        if retrieval_available and plan.get("needs_retrieval"):
            return "researcher"
        return next_stage

    return route_after_planner


# 默认（具备检索能力、无技能目录）的路由
route_after_planner = make_route_after_planner(retrieval_available=True)
