"""API 请求 / 响应模型。

API 契约与 LLM 内部模型解耦：这里不直接复用 ``app.llm.base.ChatMessage``，
以便接口结构独立演进。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]


class ChatMessageIn(BaseModel):
    role: Role
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """Phase 1 最小请求体：一段对话消息列表。"""

    messages: list[ChatMessageIn] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)


class ChatResponse(BaseModel):
    answer: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    app_env: str
    llm_provider: str
    llm_configured: bool
    # --- 展示用：界面按「图标 + 模型名」显示，而不是内部 provider id ---
    llm_label: str = ""
    llm_model: str = ""
    llm_local: bool = False


class LLMProviderInfo(BaseModel):
    """一个可选 LLM Provider 的状态（不含任何密钥信息）。"""

    id: str
    model: str
    configured: bool
    active: bool
    # --- 展示用（不含密钥）---
    label: str = ""
    base_url: str = ""
    is_local: bool = False
    managed: bool = False
    key_source: str = ""
    key_hint: str = ""


class SettingsResponse(BaseModel):
    """应用设置快照。"""

    llm_provider: str
    providers: list[LLMProviderInfo]


class LlmProviderUpdate(BaseModel):
    """切换当前 LLM Provider 的请求体。"""

    provider: str = Field(min_length=1)


class ProviderResponse(BaseModel):
    """自定义 Provider 视图（**不含密钥**）。"""

    provider_id: str
    label: str
    base_url: str
    model: str
    api_key_env: str = ""
    key_source: str = "none"
    key_hint: str = ""
    requires_api_key: bool = True
    is_local: bool = False
    timeout_seconds: float = 120.0
    max_retries: int = 2
    created_at: str = ""
    updated_at: str = ""


class ProviderListResponse(BaseModel):
    providers: list[ProviderResponse]


class ProviderCreateRequest(BaseModel):
    # 留空则默认使用模型名（界面上不该出现 custom-xxxxxxxx 这种内部 id）
    label: str | None = Field(default=None, max_length=40)
    base_url: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=120)
    api_key: str | None = None
    api_key_env: str | None = None
    requires_api_key: bool = True
    is_local: bool = False
    timeout_seconds: float = 120.0
    max_retries: int = 2


class ProviderUpdateRequest(BaseModel):
    """只传需要修改的字段；``api_key`` 缺省=保持不变，空串=清空。"""

    label: str | None = Field(default=None, min_length=1, max_length=40)
    base_url: str | None = Field(default=None, min_length=1, max_length=300)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    api_key: str | None = None
    api_key_env: str | None = None
    requires_api_key: bool | None = None
    is_local: bool | None = None
    timeout_seconds: float | None = None
    max_retries: int | None = None


class ProviderProbeRequest(BaseModel):
    """测试 Provider 连通性（编辑中的配置可直接传，已保存的传 provider_id）。"""

    base_url: str = ""
    model: str = ""
    provider_id: str | None = None
    # 编辑态前端可临时传入密钥；已保存的 Provider 一律用服务端配置
    api_key: str | None = None
    requires_api_key: bool = True
    is_local: bool = False
    timeout_seconds: float = 20.0


class ProviderProbeResponse(BaseModel):
    ok: bool
    detail: str = ""
    latency_ms: int = 0
    reply: str = ""


class ModelListResponse(BaseModel):
    ok: bool
    detail: str = ""
    models: list[str] = Field(default_factory=list)
    latency_ms: int = 0


class CategoryInfo(BaseModel):
    """知识库类别（多标签）。"""

    category_id: str
    name: str
    description: str = ""
    document_count: int = 0
    created_at: str
    updated_at: str


class CategoryListResponse(BaseModel):
    categories: list[CategoryInfo]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=200)


class DocumentCategoriesUpdate(BaseModel):
    """整组替换某文档的类别。"""

    category_ids: list[str] = Field(default_factory=list)


class TaskScope(BaseModel):
    """任务检索范围：类别与单文档的并集；都为空表示整个知识库。"""

    category_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)


class TaskScopeInfo(BaseModel):
    """结果中回显的范围：解析后的规模 + 用户的原始选择（供重跑重新解析）。"""

    label: str
    document_count: int
    category_ids: list[str] = Field(default_factory=list)
    selected_document_ids: list[str] = Field(default_factory=list)


class SkillInfo(BaseModel):
    """一个技能（Agent 可调用的结构化指令模块）。"""

    skill_id: str
    name: str
    description: str
    content: str
    enabled: bool
    builtin: bool
    created_at: str
    updated_at: str


class SkillListResponse(BaseModel):
    skills: list[SkillInfo]


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None


class TaskRequest(BaseModel):
    """提交一个 Agent 任务。"""

    query: str = Field(min_length=1)
    user_preferences: dict[str, str] = Field(default_factory=dict)
    # 检索范围（可选）：缺省或为空 = 整个知识库
    scope: TaskScope | None = None


class PlanStepOut(BaseModel):
    id: str
    type: str
    description: str


class PlanOut(BaseModel):
    goal: str
    needs_retrieval: bool
    steps: list[PlanStepOut]


class StepResultOut(BaseModel):
    step_id: str
    status: str
    summary: str


class SourceOut(BaseModel):
    """最终结果引用的来源，编号与正文 [n] 对应。"""

    index: int
    document_id: str
    filename: str
    page: int | None = None
    chunk_id: str
    score: float | None = None


class ValidationOut(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    suggested_action: str
    target: str


class TaskResponse(BaseModel):
    task_id: str
    status: str
    plan: PlanOut | None = None
    outline: list[str] = Field(default_factory=list)
    step_results: list[StepResultOut] = Field(default_factory=list)
    sources: list[SourceOut] = Field(default_factory=list)
    validation: ValidationOut | None = None
    # 全局 replan 次数
    retry_count: int = 0
    # 未通过校验的章节（如 "chapter_3"）
    failed_chapters: list[str] = Field(default_factory=list)
    final_answer: str = ""
    # 本次检索范围（回显）；None 表示整个知识库
    scope: TaskScopeInfo | None = None


class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    title: str
    chunks: int
    # 所属类别（多标签）：列表接口一次性带出，避免前端逐文档查询
    category_ids: list[str] = Field(default_factory=list)


class TaskSummaryOut(BaseModel):
    """任务列表项（不含正文，避免列表响应过大）。"""

    task_id: str
    query: str
    status: str
    created_at: str
    finished_at: str | None = None
    error_type: str | None = None
    retry_count: int = 0
    failed_chapters: list[str] = Field(default_factory=list)


class CancelTaskResponse(BaseModel):
    """取消正在运行的任务。"""

    task_id: str
    status: str


class TaskListResponse(BaseModel):
    tasks: list[TaskSummaryOut] = Field(default_factory=list)


class TaskStateResponse(BaseModel):
    """Agent checkpoint 中的结构化状态摘要（不包含消息原文与推理过程）。"""

    task_id: str
    checkpoint_id: str | None = None
    status: str | None = None
    current_step: str | None = None
    is_complete: bool = False
    retry_count: int = 0
    outline: list[str] = Field(default_factory=list)
    chapters_written: int = 0
    sources_count: int = 0


class MemoryOut(BaseModel):
    memory_id: int
    kind: str
    content: str
    source_task_id: str | None = None
    created_at: str


class MemoryProfileResponse(BaseModel):
    user_id: str
    preferences: dict[str, str] = Field(default_factory=dict)
    memories: list[MemoryOut] = Field(default_factory=list)


class SetPreferenceRequest(BaseModel):
    value: str = Field(min_length=1, max_length=200)


class AddMemoryRequest(BaseModel):
    kind: str = Field(default="fact", min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=300)
    source_task_id: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo] = Field(default_factory=list)


class TaskAttemptOut(BaseModel):
    """任务的一次运行尝试（不含结果正文，保持响应轻量）。"""

    attempt_no: int
    status: str
    started_at: str
    finished_at: str | None = None
    error_type: str | None = None
    retry_count: int = 0


class TaskDetailResponse(TaskResponse):
    """单个任务记录（含持久化元信息，AGENTS.md §18 的 GET /api/tasks/{id}）。"""

    user_id: str
    query: str
    created_at: str
    finished_at: str | None = None
    error_type: str | None = None
    # 是否正在运行 / 是否可从断点继续（前端据此显示「继续生成」按钮）
    running: bool = False
    resumable: bool = False
    # 全部运行尝试（首次执行 / 继续生成 …），保留每次的失败原因
    attempts: list[TaskAttemptOut] = Field(default_factory=list)


class DeleteDocumentResponse(BaseModel):
    document_id: str
    status: str


class ErrorResponse(BaseModel):
    """统一错误结构。``detail`` 只包含可安全展示的信息。"""

    error: str
    error_type: str
    detail: str | None = None
    # 便于失败后仍可查询任务记录（GET /api/tasks/{id}）
    task_id: str | None = None


class PresetInfo(BaseModel):
    """一条预设任务（工作台输入快捷方式）。"""

    preset_id: str
    title: str
    description: str
    query: str
    created_at: str
    updated_at: str


class PresetListResponse(BaseModel):
    presets: list[PresetInfo]


class PresetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=2000)


class PresetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, min_length=1, max_length=120)
    query: str | None = Field(default=None, min_length=1, max_length=2000)
