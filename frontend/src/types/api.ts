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
}

export interface LlmProviderInfo {
  id: string
  model: string
  configured: boolean
  active: boolean
}

export interface SettingsResponse {
  llm_provider: string
  providers: LlmProviderInfo[]
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
}

export interface SkillListResponse {
  skills: SkillInfo[]
}

export interface PresetInfo {
  preset_id: string
  title: string
  description: string
  query: string
  created_at: string
  updated_at: string
}

export interface PresetListResponse {
  presets: PresetInfo[]
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

export interface TaskResult {
  task_id: string
  status: string
  plan: Plan | null
  outline: string[]
  step_results: StepResult[]
  sources: Source[]
  validation: Validation | null
  /** 全局 replan 次数 */
  retry_count: number
  /** 未通过校验的章节，如 ["chapter_3"] */
  failed_chapters: string[]
  final_answer: string
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
}

/** 任务列表项（不含正文）。 */
export interface TaskSummary {
  task_id: string
  query: string
  status: string
  created_at: string
  finished_at?: string | null
  error_type?: string | null
  retry_count: number
  failed_chapters: string[]
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

/** 后端 SSE 推送的进度事件（见 AGENTS.md §19）。 */
export interface TaskEvent {
  task_id: string
  event: string
  step?: string | null
  status: string
  message: string
  plan?: Plan | null
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
  chapters_written?: number
  /** 重新生成：task_started 事件指向的原任务 */
  rerun_of?: string
  /** 技能事件（skill_started / skill_completed）附加字段 */
  skill_id?: string
  skill_name?: string
  summary?: string
  result?: TaskResult
}
