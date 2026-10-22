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

StepType = Literal["retrieval", "skill", "outline", "writing", "validation"]
TaskStatus = Literal["pending", "planning", "writing", "validating", "completed", "failed"]
SuggestedAction = Literal["continue", "retry_writer", "replan"]


class PlanStep(TypedDict):
    """计划中的单个步骤。

    ``type="skill"`` 的步骤必须带 ``skill_id``，指向技能目录中的技能。
    """

    id: str
    type: StepType
    description: str
    skill_id: str | None


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


class RetrievalScope(TypedDict, total=False):
    """本次任务的检索范围（提交时解析并冻结，随 checkpoint 持久化）。

    - ``document_ids``：解析并**冻结**后的文档列表，检索时实际使用；
      因此任务执行期间往类别里新增文档不会悄悄改变本次范围；
    - ``category_ids`` / ``selected_document_ids``：用户的原始选择，
      供「重新生成」重新解析与界面展示；
    - ``label``：展示用文案。
    """

    document_ids: list[str]
    category_ids: list[str]
    selected_document_ids: list[str]
    label: str


class SkillOutput(TypedDict):
    """一次技能执行的产出（追加合并，供 outline/writer 作为上下文）。"""

    skill_id: str
    skill_name: str
    step_id: str
    summary: str
    content: str


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
    # 本次任务的执行画像（模式 / 篇幅 / 校验策略 / 是否允许技能），
    # 由 app.agents.router 在进入图之前确定，随 checkpoint 持久化。
    task_profile: dict[str, object]
    # --- 会话 ---
    messages: Annotated[list[ChatMessage], add]
    user_query: str
    user_preferences: dict[str, str]
    # --- 计划 ---
    plan: Plan | None
    current_step: str | None
    step_results: Annotated[list[StepResult], add]
    # --- 检索（Phase 3）---
    # 本次任务的检索范围；None 表示整个知识库
    retrieval_scope: RetrievalScope | None
    retrieved_documents: Annotated[list[RetrievedDocument], add]
    # --- 技能（Agent 可调用的指令模块，按计划中的 skill 步骤逐个执行）---
    skill_outputs: Annotated[list[SkillOutput], add]
    # --- 生成 ---
    outline: list[Section]
    # 覆盖语义、与 outline 下标对齐：支持重写某一章、跳过失败章节与 replan 后重置
    sections: list[Section]
    draft: str
    # --- 验证与重试（Phase 4B）---
    # 最近一次校验结果
    validation_result: ValidationResult | None
    # 章节 -> 已失败次数（每章独立预算，上限 MAX_RETRIES）
    retry_counts: dict[str, int]
    # 章节 -> 最近一次校验结果（"document" 表示整篇校验）
    chapter_validations: dict[str, ValidationResult]
    # 全局 replan 次数（replan 是计划级操作，单独计数，避免无限循环）
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
    retrieval_scope: RetrievalScope | None = None,
    task_profile: dict[str, object] | None = None,
) -> AgentState:
    """构造一次任务运行的初始状态。

    ``task_profile`` 缺省时由调用方（TaskService）补齐；直接调用图的测试
    可以不传，路由会按 ``longform`` 兼容旧行为。
    """
    return AgentState(
        task_id=task_id,
        task_profile=task_profile or {},
        messages=[ChatMessage(role="user", content=query)],
        user_query=query,
        user_preferences=user_preferences or {},
        plan=None,
        current_step=None,
        step_results=[],
        retrieval_scope=retrieval_scope,
        retrieved_documents=[],
        skill_outputs=[],
        outline=[],
        sections=[],
        draft="",
        validation_result=None,
        retry_counts={},
        chapter_validations={},
        retry_count=0,
        final_answer="",
        task_status="pending",
        is_complete=False,
    )
