"""API 请求 / 响应模型。

API 契约与 LLM 内部模型解耦：这里不直接复用 ``app.llm.base.ChatMessage``，
以便接口结构独立演进。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.state import RetrievalMode

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
    flavor: str = "openai"
    disable_thinking: bool = False
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
    # 线路协议：openai（/v1 兼容）或 ollama（原生 /api/chat，可关闭思考）
    flavor: str = "openai"
    # 关闭思考：只对本地 Ollama（flavor=ollama）生效；openai 协议下会被忽略，
    # 因此前端在非 ollama 协议时禁用该勾选（见 Providers.tsx）。
    disable_thinking: bool = False
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
    flavor: str = "openai"
    disable_thinking: bool = False


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
    flavor: str | None = None
    disable_thinking: bool | None = None


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
    # 由文档生成时的来源文件名（手写/内置为 None）
    source_filename: str | None = None
    # L3 附件数量与其中的脚本数量（目录扫描派生，不落盘）
    resource_count: int = 0
    script_count: int = 0


class SkillListResponse(BaseModel):
    skills: list[SkillInfo]


class SkillResourceInfo(BaseModel):
    """技能按需附件（L3）：目录只暴露 name，正文按请求注入。"""

    resource_id: str
    skill_id: str
    name: str
    content: str
    created_at: str
    updated_at: str


class SkillResourceListResponse(BaseModel):
    resources: list[SkillResourceInfo]


class SkillResourceCreate(BaseModel):
    # 文件制附件用相对技能根目录的 POSIX 路径（如 references/checklist.md）
    name: str = Field(min_length=1, max_length=260)
    content: str = Field(min_length=1, max_length=20000)


class SkillResourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=260)
    content: str | None = Field(default=None, min_length=1, max_length=20000)


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    source_filename: str | None = Field(default=None, max_length=260)


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None


class SkillGenerateRequest(BaseModel):
    """从知识库文档生成技能草稿（只生成，不落库）。"""

    # 一次最多 3 篇：多篇会被拼接后一起提炼，过多会挤占上下文
    document_ids: list[str] = Field(min_length=1, max_length=3)
    hint: str = Field(default="", max_length=200)


class SkillDraft(BaseModel):
    """生成的技能草稿：用户在前端确认/编辑后再走 ``POST /api/skills`` 保存。"""

    name: str
    description: str
    content: str
    source_filename: str | None = None


class SkillDuplicate(BaseModel):
    """草稿与已有技能同名（供前端提示「更新已有」而不是重复新建）。"""

    skill_id: str
    name: str


class SkillGenerateResponse(BaseModel):
    draft: SkillDraft
    # 文档超长时只用了前 N 字，前端须如实提示
    truncated: bool = False
    # 不影响保存、但值得提醒用户的问题（如描述缺少触发条件）
    warnings: list[str] = Field(default_factory=list)
    duplicate_of: SkillDuplicate | None = None


class SkillPackageResource(BaseModel):
    """技能包预览中的一个附件（相对路径 + 文本内容）。"""

    name: str
    content: str


class SkillImportPreview(BaseModel):
    """技能包解析结果（尚未落盘，需用户确认）。"""

    token: str
    name: str
    description: str
    content: str
    resources: list[SkillPackageResource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggested_skill_id: str | None = None
    source_filename: str | None = None
    # 预览在内存中的存活时间（秒）
    expires_in: int


class SkillImportConfirm(BaseModel):
    token: str = Field(min_length=1, max_length=64)


TaskDepth = Literal["auto", "brief", "longform"]


class TaskRequest(BaseModel):
    """提交一个 Agent 任务。"""

    query: str = Field(min_length=1)
    user_preferences: dict[str, str] = Field(default_factory=dict)
    # 检索范围（可选）：缺省或为空 = 整个知识库
    scope: TaskScope | None = None
    # 检索模式：
    # - all（默认）：整个知识库，按任务需要检索；
    # - selected：仅检索 scope 指定的类别 / 文档（必须至少有一项）；
    # - none：本次不检索知识库，只用通用知识。
    # 缺省时兼容旧客户端：scope 非空按 selected，否则 all。
    retrieval_mode: RetrievalMode | None = None
    # 执行深度：auto = 由确定性规则选择；brief = 简洁回答；longform = 长文流水线
    depth: TaskDepth = "auto"
    # 技能默认关闭（显式 opt-in），避免简单任务被技能步骤放大
    use_skills: bool = False


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


class UsageOut(BaseModel):
    """一次任务运行的模型用量（只统计本次运行，不累加历史尝试）。

    缓存由上游决定：``cache_reported=False`` 表示该模型不提供缓存指标
    （如 Ollama），前端应显示「—」而不是 0%。
    """

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    cache_reported: bool = False
    # 每次调用的墙钟时间之和（含网络排队），单位秒
    llm_seconds: float = 0.0
    # completion_tokens / llm_seconds，含网络的输出吞吐
    tokens_per_second: float = 0.0
    models: list[str] = Field(default_factory=list)


class TaskProfileOut(BaseModel):
    """任务执行画像（由确定性路由产生，0 次 LLM 调用）。"""

    mode: str
    needs_retrieval: bool = False
    target_chars: int = 0
    max_sections: int = 1
    validation: str = "none"
    apply_preferences: str = "all"
    allow_skills: bool = False
    thinking: bool | None = None
    estimated_calls: int | None = None
    reason: str = ""


class WritingBudgetOut(BaseModel):
    """本次长文的资料量自适应写作预算。"""

    requested_chars: int
    source_chars: int
    source_count: int
    effective_chars: int
    source_limited: bool = False
    no_sources: bool = False
    recommended_sections: int = 1
    reason: str = ""


class TaskResponse(BaseModel):
    task_id: str
    status: str
    # direct / brief / longform；旧记录为 None
    mode: str | None = None
    profile: TaskProfileOut | None = None
    plan: PlanOut | None = None
    # 资料量自适应预算；旧任务 / 轻量回答为 None
    writing_budget: WritingBudgetOut | None = None
    outline: list[str] = Field(default_factory=list)
    step_results: list[StepResultOut] = Field(default_factory=list)
    sources: list[SourceOut] = Field(default_factory=list)
    validation: ValidationOut | None = None
    # 全局 replan 次数
    retry_count: int = 0
    # 未通过校验的章节（如 "chapter_3"）
    failed_chapters: list[str] = Field(default_factory=list)
    final_answer: str = ""
    # 本次检索模式：all / selected / none
    retrieval_mode: RetrievalMode | None = None
    # 本次检索范围（回显）；None 表示整个知识库 / 不检索
    scope: TaskScopeInfo | None = None
    # 本次运行的模型用量；旧记录没有该字段时为 None
    usage: UsageOut | None = None


class TaskEmailRequest(BaseModel):
    """把任务正文发送到指定邮箱。"""

    # 具体格式由服务层校验：非法地址返回 400，而不是 FastAPI 的 422 结构
    to: str = Field(default="")


class TaskEmailResponse(BaseModel):
    """邮件发送结果（收件人已脱敏，绝不回传完整地址）。"""

    status: str = "sent"
    task_id: str
    to: str
    subject: str


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
    mode: str | None = None
    created_at: str
    finished_at: str | None = None
    error_type: str | None = None
    retry_count: int = 0
    failed_chapters: list[str] = Field(default_factory=list)
    # 仅运行中任务由进程内注册表填充（§19 事件名与消息），供顶栏胶囊展示阶段
    stage: str | None = None
    message: str | None = None


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


class MemoryPackageItemOut(BaseModel):
    kind: str
    content: str


class MemoryImportPreview(BaseModel):
    """长期记忆导入预览（只列出真正会新增的项）。"""

    token: str
    preferences: dict[str, str] = Field(default_factory=dict)
    memories: list[MemoryPackageItemOut] = Field(default_factory=list)
    skipped_preferences: list[str] = Field(default_factory=list)
    skipped_memories: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_filename: str | None = None
    expires_in: int


class MemoryImportResultOut(BaseModel):
    preferences: list[str] = Field(default_factory=list)
    memories: list[str] = Field(default_factory=list)
    skipped_preferences: list[str] = Field(default_factory=list)
    skipped_memories: list[str] = Field(default_factory=list)


class ImportConfirmRequest(BaseModel):
    """通用「确认导入」请求：消费预览 token。"""

    token: str = Field(min_length=1, max_length=64)


class SetPreferenceRequest(BaseModel):
    value: str = Field(min_length=1, max_length=200)


class AddMemoryRequest(BaseModel):
    kind: str = Field(default="fact", min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=300)
    source_task_id: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo] = Field(default_factory=list)


class KnowledgeImportDocumentOut(BaseModel):
    filename: str
    size: int
    category_ids: list[str] = Field(default_factory=list)


class KnowledgeImportPreview(BaseModel):
    """知识库导入预览（确认后会重新解析、切分并建立向量索引）。"""

    token: str
    documents: list[KnowledgeImportDocumentOut] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_filename: str | None = None
    expires_in: int


class KnowledgeImportFailureOut(BaseModel):
    filename: str
    message: str


class KnowledgeImportResultOut(BaseModel):
    imported: list[DocumentInfo] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[KnowledgeImportFailureOut] = Field(default_factory=list)
    categories_created: list[str] = Field(default_factory=list)


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
    # 绑定的检索范围（None = 未绑定：运行时用工作台当前选择；全部/部分由该字段体现）
    scope: TaskScope | None = None
    # 工作台点击卡片是否直接执行（默认 False = 仅填入输入框待确认）
    auto_run: bool = False
    # 工作台展示顺序（越小越靠前；新建预设追加到末尾）
    sort_order: int = 0
    created_at: str
    updated_at: str


class PresetListResponse(BaseModel):
    presets: list[PresetInfo]


class PresetOrderRequest(BaseModel):
    """按完整列表重排预设；必须包含当前全部 preset_id。"""

    preset_ids: list[str] = Field(min_length=1)


class PresetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=2000)
    # 可选绑定范围：缺省/空 = 不绑定（运行时沿用当前选择）
    scope: TaskScope | None = None
    auto_run: bool = False


class PresetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, min_length=1, max_length=120)
    query: str | None = Field(default=None, min_length=1, max_length=2000)
    # 注意：scope 用 model_fields_set 判「是否提供」——`null` 是合法值（清除绑定）
    scope: TaskScope | None = None
    auto_run: bool | None = None


class PresetImportItem(BaseModel):
    title: str
    description: str
    query: str
    auto_run: bool = False
    scope: TaskScope | None = None


class PresetImportPreview(BaseModel):
    """预设导入预览（只列出真正会新增的项）。"""

    token: str
    presets: list[PresetImportItem] = Field(default_factory=list)
    skipped_duplicates: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_filename: str | None = None
    expires_in: int


class PresetImportResult(BaseModel):
    imported: list[PresetInfo] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
