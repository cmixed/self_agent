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

export interface ApiErrorBody {
  error: string
  error_type: string
  detail?: string | null
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
  passed?: boolean
  target?: string
  issues?: string[]
  suggested_action?: string
  retry_count?: number
  exhausted?: boolean
  error_type?: string
  result?: TaskResult
}
