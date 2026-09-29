import type {
  ApiErrorBody,
  ChatMessage,
  ChatResponse,
  HealthResponse,
  TaskEvent,
} from '../types/api'

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

async function toApiError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody = { error: 'request_failed', error_type: 'unknown' }
  try {
    body = (await response.json()) as ApiErrorBody
  } catch {
    // 后端可能返回非 JSON 错误页，忽略解析失败
  }
  return new ApiError(response.status, body)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    throw await toApiError(response)
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

/**
 * 提交任务并消费 SSE 进度流。
 *
 * 用 fetch + ReadableStream 而非 EventSource：EventSource 只支持 GET，
 * 而任务需要 POST 请求体。
 */
export async function streamTask(
  query: string,
  onEvent: (event: TaskEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/tasks/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ query }),
    signal,
  })

  if (!response.ok) {
    throw await toApiError(response)
  }
  if (!response.body) {
    throw new ApiError(500, { error: 'no_stream', error_type: 'no_stream' })
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let separator = buffer.indexOf('\n\n')
    while (separator !== -1) {
      const frame = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data: ')) continue
        onEvent(JSON.parse(line.slice('data: '.length)) as TaskEvent)
      }
      separator = buffer.indexOf('\n\n')
    }
  }
}
