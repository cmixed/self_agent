import type { ApiErrorBody, ChatMessage, ChatResponse, HealthResponse } from '../types/api'

const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly errorType: string

  constructor(status: number, body: ApiErrorBody) {
    super(body.detail || body.error || `请求失败（HTTP ${status}）`)
    this.name = 'ApiError'
    this.status = status
    this.errorType = body.error_type ?? 'unknown'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!response.ok) {
    let body: ApiErrorBody = { error: 'request_failed', error_type: 'unknown' }
    try {
      body = (await response.json()) as ApiErrorBody
    } catch {
      // 后端可能返回非 JSON 错误页，忽略解析失败
    }
    throw new ApiError(response.status, body)
  }

  return (await response.json()) as T
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health')
}

export function sendChat(messages: ChatMessage[], signal?: AbortSignal): Promise<ChatResponse> {
  return request<ChatResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify({ messages }),
    signal,
  })
}
