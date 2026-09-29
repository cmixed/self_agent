"""Planner 节点。

职责（AGENTS.md §8）：理解任务、判断是否需要知识库检索、拆解为结构化步骤。
输出必须是结构化数据（Pydantic 校验），解析失败时有限重试。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, Plan, PlanStep, StepResult

logger = get_logger(__name__)

_PLANNER_SYSTEM_PROMPT = """你是一个任务规划器。请把用户的复杂任务拆解为可执行步骤。

要求：
1. 只输出 JSON，不要输出任何解释文字或 Markdown 代码块。
2. JSON 结构必须为：
   {"goal": "任务目标", "needs_retrieval": true/false,
    "steps": [{"id": "步骤id", "type": "步骤类型", "description": "步骤说明"}]}
3. "type" 取值：retrieval（检索知识库）、outline（生成大纲）、
   writing（撰写内容）、validation（检查内容）。
4. "needs_retrieval" 表示是否需要检索用户的个人知识库资料。
5. 步骤数量控制在 2-6 个，按执行顺序排列。
"""


class PlanStepModel(BaseModel):
    """Planner 输出的单个步骤（用于 Schema 校验）。"""

    id: str = Field(min_length=1)
    type: Literal["retrieval", "outline", "writing", "validation"]
    description: str = Field(min_length=1)


class PlanModel(BaseModel):
    """Planner 输出的结构化计划。"""

    goal: str = Field(min_length=1)
    needs_retrieval: bool
    steps: list[PlanStepModel] = Field(min_length=1)


def _render_planner_input(state: AgentState) -> str:
    parts = [f"用户任务：{state.get('user_query', '')}"]
    preferences = state.get("user_preferences") or {}
    if preferences:
        rendered = "；".join(f"{key}={value}" for key, value in preferences.items())
        parts.append(f"用户偏好：{rendered}")
    return "\n".join(parts)


def make_planner_node(
    llm: LLMProvider, *, max_retries: int = 2
) -> Callable[[AgentState], Awaitable[dict]]:
    """构造绑定了 LLM 的 planner 节点。"""

    async def planner_node(state: AgentState) -> dict:
        messages = [
            ChatMessage(role="system", content=_PLANNER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=_render_planner_input(state)),
        ]
        plan_model = await llm.chat_structured(
            messages, PlanModel, temperature=0.0, max_retries=max_retries
        )

        steps: list[PlanStep] = [
            PlanStep(id=step.id, type=step.type, description=step.description)
            for step in plan_model.steps
        ]
        plan: Plan = Plan(
            goal=plan_model.goal,
            needs_retrieval=plan_model.needs_retrieval,
            steps=steps,
        )

        summary = f"生成 {len(steps)} 个步骤，needs_retrieval={plan_model.needs_retrieval}"
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


def make_route_after_planner(*, retrieval_available: bool) -> Callable[[AgentState], str]:
    """构造 planner 之后的路由函数。

    有计划且需要检索（且检索能力可用）→ researcher；否则 → writer；无计划 → 安全结束。
    """

    def route_after_planner(state: AgentState) -> str:
        plan = state.get("plan")
        if not plan:
            return "end"
        if retrieval_available and plan.get("needs_retrieval"):
            return "researcher"
        return "outline"

    return route_after_planner


# 默认（具备检索能力）的路由
route_after_planner = make_route_after_planner(retrieval_available=True)
