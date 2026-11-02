export type Role = 'system' | 'user' | 'assistant'

export interface ChatMessage {
  role: Role
  content: string
}

export interface ChatResponse {
  answer: string
  model: string
  usage: Record<string, number>
}

export interface HealthResponse {
  status: string
  app_env: string
  llm_provider: string
  llm_configured: boolean
  /** 展示用：Provider 名称（自定义 Provider 为用户命名或模型名） */
  llm_label?: string
  /** 展示用：当前模型名（界面按「图标 + 模型名」显示） */
  llm_model?: string
  /** 是否本地模型服务（决定图标与提示文案） */
  llm_local?: boolean
}

export interface ProviderInfo {
  provider_id: string
  label: string
  base_url: string
  model: string
  api_key_env: string
  /** 线路协议：openai（/v1 兼容）或 ollama（原生 /api/chat） */
  flavor: string
  /** 关闭思考模式（仅 flavor=ollama 生效） */
  disable_thinking: boolean
  /** 密钥来源：env（环境变量优先）/ db（本地保存）/ none（无需密钥） */
  key_source: string
  /** 仅末 4 位提示，绝不含完整密钥 */
  key_hint: string
  requires_api_key: boolean
  is_local: boolean
  timeout_seconds: number
  max_retries: number
  created_at: string
  updated_at: string
}

export interface ProviderListResponse {
  providers: ProviderInfo[]
}

export interface ProviderProbeResponse {
  ok: boolean
  detail: string
  latency_ms: number
  reply: string
}

export interface ModelListResponse {
  ok: boolean
  detail: string
  models: string[]
  latency_ms: number
}

export interface LlmProviderOption {
  id: string
  model: string
  configured: boolean
  active: boolean
  label: string
  base_url: string
  is_local: boolean
  /** true = 用户自定义（可在「模型服务」页编辑/删除） */
  managed: boolean
  /** 线路协议：openai（/v1）或 ollama（原生 /api/chat） */
  flavor: string
  /** 是否已关闭思考模式（仅 ollama 协议生效） */
  disable_thinking: boolean
  key_source: string
  key_hint: string
}

export interface SettingsResponse {
  llm_provider: string
  providers: LlmProviderOption[]
}

export interface CategoryInfo {
  category_id: string
  name: string
  description: string
  document_count: number
  created_at: string
  updated_at: string
}

export interface CategoryListResponse {
  categories: CategoryInfo[]
}

/** 任务检索范围：类别与单文档的并集；都为空表示整个知识库。 */
export interface TaskScope {
  category_ids: string[]
  document_ids: string[]
}

/** 检索模式：全部知识库 / 指定范围 / 不检索。 */
export type RetrievalMode = 'all' | 'selected' | 'none'

export interface TaskScopeInfo {
  label: string
  document_count: number
  category_ids: string[]
  selected_document_ids: string[]
}

export interface SkillInfo {
  skill_id: string
  name: string
  description: string
  content: string
  enabled: boolean
  builtin: boolean
  created_at: string
  updated_at: string
  /** 由文档生成时的来源文件名（手写/内置为 null） */
  source_filename?: string | null
  /** L3 附件数量与其中的脚本数量 */
  resource_count: number
  script_count: number
}

export interface SkillListResponse {
  skills: SkillInfo[]
}

/** 技能包（zip）预览里的一个附件：相对技能根目录的路径 + 文本内容。 */
export interface SkillPackageResource {
  name: string
  content: string
}

/** 技能包解析结果（尚未落盘，需确认）。 */
export interface SkillImportPreview {
  token: string
  name: string
  description: string
  content: string
  resources: SkillPackageResource[]
  warnings: string[]
  suggested_skill_id: string | null
  source_filename: string | null
  /** 预览在内存中的存活时间（秒） */
  expires_in: number
}

/** 技能按需附件（L3）：目录只暴露 name，正文在模型请求时加载。 */
export interface SkillResourceInfo {
  resource_id: string
  skill_id: string
  name: string
  content: string
  created_at: string
  updated_at: string
}

export interface SkillResourceListResponse {
  resources: SkillResourceInfo[]
}

export interface SkillDraft {
  name: string
  description: string
  content: string
  source_filename: string | null
}

export interface SkillGenerateResponse {
  draft: SkillDraft
  /** 长文档超出分块上限、或生成结果被预算截断 */
  truncated: boolean
  /** 不影响保存、但值得提醒的问题 */
  warnings: string[]
  /** 与已有技能同名（建议改编辑已有而不是重复新建） */
  duplicate_of: { skill_id: string; name: string } | null
}

export interface PresetInfo {
  preset_id: string
  title: string
  description: string
  query: string
  /** 绑定的检索范围；null/缺省 = 未绑定（运行时用工作台当前选择）。 */
  scope?: TaskScope | null
  /** 已废弃：工作台统一为「点击卡片填入、按钮直接运行」，该字段仅保留兼容。 */
  auto_run: boolean
  /** 工作台展示顺序（越小越靠前；新建预设追加到末尾）。 */
  sort_order: number
  created_at: string
  updated_at: string
}

export interface PresetListResponse {
  presets: PresetInfo[]
}

// --- 统一导入导出 ---

export interface ImportConfirmPayload {
  token: string
}

export interface PresetImportItem {
  title: string
  description: string
  query: string
  /** 已废弃，导入时忽略。 */
  auto_run: boolean
  scope?: TaskScope | null
}

export interface PresetImportPreview {
  token: string
  presets: PresetImportItem[]
  skipped_duplicates: string[]
  warnings: string[]
  source_filename?: string | null
  expires_in: number
}

export interface PresetImportResult {
  imported: PresetInfo[]
  skipped: string[]
}

export interface BackupSectionPreview {
  key: string
  label: string
  summary: string
  warnings: string[]
}

export interface BackupImportPreview {
  token: string
  sections: BackupSectionPreview[]
  warnings: string[]
  source_filename?: string | null
  expires_in: number
}

export interface BackupSectionResult {
  key: string
  label: string
  summary: string
  failed: string[]
}

export interface BackupImportResult {
  sections: BackupSectionResult[]
  warnings: string[]
}

export interface ApiErrorBody {
  error: string
  error_type: string
  detail?: string | null
  task_id?: string | null
}

export interface PlanStep {
  id: string
  type: string
  description: string
}

export interface Plan {
  goal: string
  needs_retrieval: boolean
  steps: PlanStep[]
}

export interface StepResult {
  step_id: string
  status: string
  summary: string
}

export interface Source {
  index: number
  document_id: string
  filename: string
  page?: number | null
  chunk_id: string
  score?: number | null
}

export interface Validation {
  passed: boolean
  issues: string[]
  suggested_action: string
  target: string
}

/** 一次任务运行的模型用量（后端只统计本次运行，不累加历史尝试）。 */
export interface TokenUsage {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  /** 缓存命中的输入 token（DeepSeek / OpenAI 兼容的上报口径） */
  cache_hit_tokens: number
  cache_miss_tokens: number
  /** 上游是否上报缓存指标；false 时前端显示「—」而不是 0% */
  cache_reported: boolean
  /** 每次调用墙钟时间之和（含网络），单位秒 */
  llm_seconds: number
  /** 输出吞吐：completion_tokens / llm_seconds */
  tokens_per_second: number
  models: string[]
}

export type TaskDepth = 'auto' | 'brief' | 'longform'

/** 输出方式：正常生成内容 / 直接输出知识库原文。 */
export type OutputMode = 'generate' | 'verbatim'

/** 直接输出原文时选中的文档（正文在 final_answer，不含在这里）。 */
export interface VerbatimInfo {
  document_id: string
  filename: string
  title: string
  chars: number
  /** explicit / filename / single / retrieval / llm */
  selection: string
  reason: string
}

/** 任务结束后自动写入的长期记忆（只含真正写入的条目）。 */
export interface MemoryUpdates {
  attempted: boolean
  /** longform / signal:<命中短语> */
  trigger: string
  preferences: { key: string; value: string }[]
  memories: { kind: string; content: string }[]
  skipped: number
}

/** 后端确定性路由产生的执行画像。 */
export interface TaskProfile {
  mode: string
  needs_retrieval: boolean
  target_chars: number
  max_sections: number
  validation: string
  apply_preferences: string
  allow_skills: boolean
  thinking?: boolean | null
  estimated_calls?: number | null
  reason: string
}

/** 资料量自适应写作预算。 */
export interface WritingBudget {
  requested_chars: number
  source_chars: number
  source_count: number
  effective_chars: number
  source_limited: boolean
  no_sources: boolean
  recommended_sections: number
  reason: string
}

export interface TaskResult {
  task_id: string
  status: string
  /** direct / brief / longform / verbatim（旧记录可能没有） */
  mode?: string | null
  profile?: TaskProfile | null
  /** generate / verbatim；旧记录缺省为 generate */
  output_mode?: OutputMode | null
  /** 直接输出原文时回显的文档（不含正文） */
  verbatim?: VerbatimInfo | null
  /** 任务结束后自动提取的长期记忆（未触发时为 null） */
  memory_updates?: MemoryUpdates | null
  plan: Plan | null
  /** 旧任务 / 轻量回答可能没有 */
  writing_budget?: WritingBudget | null
  outline: string[]
  step_results: StepResult[]
  sources: Source[]
  validation: Validation | null
  /** 全局 replan 次数 */
  retry_count: number
  /** 未通过校验的章节，如 ["chapter_3"] */
  failed_chapters: string[]
  final_answer: string
  /** 本次检索模式：all / selected / none */
  retrieval_mode?: RetrievalMode | null
  /** 本次检索范围（回显）；null 表示整个知识库 / 不检索 */
  scope?: TaskScopeInfo | null
  /** 本次运行的 token / 缓存 / 速度；旧记录为 null */
  usage?: TokenUsage | null
}

export interface TaskAttempt {
  attempt_no: number
  status: string
  started_at: string
  finished_at?: string | null
  error_type?: string | null
  retry_count: number
}

export interface TaskDetail extends TaskResult {
  user_id: string
  query: string
  created_at: string
  finished_at?: string | null
  error_type?: string | null
  /** 任务正在运行中（前端据此隐藏继续/重新生成按钮） */
  running?: boolean
  /** 存在可用检查点，可从断点继续生成 */
  resumable?: boolean
  /** 每次运行尝试（首次执行 / 继续生成 …） */
  attempts?: TaskAttempt[]
}

/** 把任务正文发送到邮箱的结果（收件人已脱敏）。 */
export interface TaskEmailResponse {
  status: string
  task_id: string
  to: string
  subject: string
}

/** 任务列表项（不含正文）。 */
export interface TaskSummary {
  task_id: string
  query: string
  status: string
  mode?: string | null
  created_at: string
  finished_at?: string | null
  error_type?: string | null
  retry_count: number
  failed_chapters: string[]
  /** 运行中任务：最近一次事件名（如 writer_started），由后端进程内事件通道填充 */
  stage?: string | null
  /** 运行中任务：最近一次事件的可读消息（如「正在撰写第 2 章」） */
  message?: string | null
}

export interface TaskListResponse {
  tasks: TaskSummary[]
}

/** Agent checkpoint 的结构化状态摘要。 */
export interface TaskState {
  task_id: string
  checkpoint_id?: string | null
  status?: string | null
  current_step?: string | null
  is_complete: boolean
  retry_count: number
  outline: string[]
  chapters_written: number
  sources_count: number
}

export interface DocumentInfo {
  document_id: string
  filename: string
  title: string
  chunks: number
  /** 所属类别（多标签），由列表接口一次性带出 */
  category_ids: string[]
}

export interface KnowledgeImportDocument {
  filename: string
  size: number
  category_ids: string[]
}

export interface KnowledgeImportPreview {
  token: string
  documents: KnowledgeImportDocument[]
  categories: string[]
  skipped: string[]
  warnings: string[]
  source_filename?: string | null
  expires_in: number
}

export interface KnowledgeImportFailure {
  filename: string
  message: string
}

export interface KnowledgeImportResult {
  imported: DocumentInfo[]
  skipped: string[]
  failed: KnowledgeImportFailure[]
  categories_created: string[]
}

export interface MemoryRecord {
  memory_id: number
  kind: string
  content: string
  source_task_id?: string | null
  created_at: string
}

export interface MemoryProfile {
  user_id: string
  preferences: Record<string, string>
  memories: MemoryRecord[]
}

export interface MemoryPackageItem {
  kind: string
  content: string
}

export interface MemoryImportPreview {
  token: string
  preferences: Record<string, string>
  memories: MemoryPackageItem[]
  skipped_preferences: string[]
  skipped_memories: string[]
  warnings: string[]
  source_filename?: string | null
  expires_in: number
}

export interface MemoryImportResult {
  preferences: string[]
  memories: string[]
  skipped_preferences: string[]
  skipped_memories: string[]
}

/** 后端 SSE 推送的进度事件（见 AGENTS.md §19）。 */
export interface TaskEvent {
  task_id: string
  event: string
  step?: string | null
  status: string
  message: string
  /** task_started / task_completed：本次执行模式与画像 */
  mode?: string | null
  profile?: TaskProfile | null
  /** task_started / task_completed：输出方式 */
  output_mode?: OutputMode | null
  /** verbatim_completed：本次直接输出的文档（正文在 result.final_answer） */
  document_id?: string
  filename?: string
  chars?: number
  selection?: string
  reason?: string
  /** task_started / task_resumed：检索模式 */
  retrieval_mode?: RetrievalMode
  plan?: Plan | null
  writing_budget?: WritingBudget | null
  outline?: string[]
  retrieved_count?: number
  sources?: Source[]
  passed?: boolean
  target?: string
  issues?: string[]
  suggested_action?: string
  retry_count?: number
  exhausted?: boolean
  error_type?: string
  /** 内容被输出长度上限截断（outline / writer 事件） */
  truncated?: boolean
  /** 断点续跑：task_resumed 事件 */
  resumed?: boolean
  /** 本次检索范围（task_resumed 快照 / 结果回显） */
  scope?: TaskScopeInfo | null
  chapters_written?: number
  /** 重新生成：task_started 事件指向的原任务 */
  rerun_of?: string
  /** 技能事件（skill_started / skill_completed）附加字段 */
  skill_id?: string
  skill_name?: string
  summary?: string
  /** memory_updated：本次自动写入的长期记忆 */
  memory_updates?: MemoryUpdates | null
  result?: TaskResult
}
