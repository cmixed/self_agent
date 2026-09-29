"""Agent 统一状态（AgentState）。

集中定义，节点只返回增量更新，由 reducer 合并（见 AGENTS.md §6）。
字段一次性按 §6 定义完整：Phase 3-5 只填充不改造，避免频繁改动 State。

LangGraph 约定：
- ``Annotated[..., add]`` 表示该 channel 追加合并；
- 其余 channel 为覆盖语义。
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict

from app.llm.base import ChatMessage

StepType = Literal["retrieval", "outline", "writing", "validation"]
TaskStatus = Literal["pending", "planning", "writing", "validating", "completed", "failed"]
SuggestedAction = Literal["continue", "retry_writer", "replan"]


class PlanStep(TypedDict):
    """计划中的单个步骤。"""

    id: str
    type: StepType
    description: str


class Plan(TypedDict):
    """Planner 输出的结构化计划。"""

    goal: str
    needs_retrieval: bool
    steps: list[PlanStep]


class StepResult(TypedDict):
    """单个步骤的执行结果。"""

    step_id: str
    status: Literal["ok", "error"]
    summary: str


class RetrievedDocument(TypedDict):
    """检索到的知识库片段（Phase 3 使用）。"""

    document_id: str
    filename: str
    page: int | None
    chunk_id: str
    content: str
    score: float | None


class Section(TypedDict):
    """长文中的一个章节。"""

    title: str
    content: str


class ValidationResult(TypedDict):
    """Validator 输出（§16）。"""

    passed: bool
    issues: list[str]
    suggested_action: SuggestedAction
    # 校验对象：``"document"`` 或 ``"chapter_N"``（重试时据此定位要重写哪一章）
    target: str


class AgentState(TypedDict, total=False):
    """LangGraph 全局状态。"""

    # --- 元数据 ---
    task_id: str
    # --- 会话 ---
    messages: Annotated[list[ChatMessage], add]
    user_query: str
    user_preferences: dict[str, str]
    # --- 计划 ---
    plan: Plan | None
    current_step: str | None
    step_results: Annotated[list[StepResult], add]
    # --- 检索（Phase 3）---
    retrieved_documents: Annotated[list[RetrievedDocument], add]
    # --- 生成 ---
    outline: list[Section]
    # 覆盖语义（writer 每次返回完整列表）：支持重写某一章与 replan 后重置
    sections: list[Section]
    draft: str
    # --- 验证与重试（Phase 4B）---
    validation_result: ValidationResult | None
    retry_count: int
    # --- 输出 ---
    final_answer: str
    task_status: TaskStatus
    is_complete: bool


def initial_state(
    query: str,
    *,
    task_id: str,
    user_preferences: dict[str, str] | None = None,
) -> AgentState:
    """构造一次任务运行的初始状态。"""
    return AgentState(
        task_id=task_id,
        messages=[ChatMessage(role="user", content=query)],
        user_query=query,
        user_preferences=user_preferences or {},
        plan=None,
        current_step=None,
        step_results=[],
        retrieved_documents=[],
        outline=[],
        sections=[],
        draft="",
        validation_result=None,
        retry_count=0,
        final_answer="",
        task_status="pending",
        is_complete=False,
    )
