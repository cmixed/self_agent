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
