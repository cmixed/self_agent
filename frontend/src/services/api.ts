import type {
  ApiErrorBody,
  ChatMessage,
  ChatResponse,
  DocumentInfo,
  HealthResponse,
  MemoryProfile,
  MemoryRecord,
  SettingsResponse,
  TaskDetail,
  TaskEvent,
  TaskListResponse,
  TaskState,
} from '../types/api'

const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly errorType: string
  readonly taskId: string | null

  constructor(status: number, body: ApiErrorBody) {
    super(body.detail || body.error || `请求失败（HTTP ${status}）`)
    this.name = 'ApiError'
    this.status = status
    this.errorType = body.error_type ?? 'unknown'
    this.taskId = body.task_id ?? null
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

// --- 应用设置（LLM Provider 切换） ---

export function getSettings(): Promise<SettingsResponse> {
  return request<SettingsResponse>('/settings')
}

/** 切换当前 LLM Provider（后端立即生效并持久化；未配置密钥时返回 409）。 */
export function updateLlmProvider(provider: string): Promise<SettingsResponse> {
  return request<SettingsResponse>('/settings/llm-provider', {
    method: 'PUT',
    body: JSON.stringify({ provider }),
  })
}

export function sendChat(messages: ChatMessage[], signal?: AbortSignal): Promise<ChatResponse> {
  return request<ChatResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify({ messages }),
    signal,
  })
}

// --- 任务 ---

export function listTasks(limit = 20): Promise<TaskListResponse> {
  return request<TaskListResponse>(`/tasks?limit=${limit}`)
}

export function getTask(taskId: string): Promise<TaskDetail> {
  return request<TaskDetail>(`/tasks/${taskId}`)
}

export function getTaskState(taskId: string): Promise<TaskState> {
  return request<TaskState>(`/tasks/${taskId}/state`)
}

/** 取消正在运行的任务（后端会中断进行中的模型调用并把运行标记为 cancelled）。 */
export function cancelTask(taskId: string): Promise<{ task_id: string; status: string }> {
  return request<{ task_id: string; status: string }>(`/tasks/${taskId}/cancel`, {
    method: 'POST',
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

// --- 知识库文档 ---

export function listDocuments(): Promise<{ documents: DocumentInfo[] }> {
  return request<{ documents: DocumentInfo[] }>('/documents')
}

export function deleteDocument(documentId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/documents/${documentId}`, { method: 'DELETE' })
}

/** 上传并索引文档（multipart：不要手动设置 Content-Type，交给浏览器带 boundary）。 */
export async function uploadDocument(file: File): Promise<DocumentInfo> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${API_BASE}/documents/upload`, { method: 'POST', body: form })
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as DocumentInfo
}

/** 知识库文档原文件的访问地址（download=true 时为附件下载，否则内联预览）。 */
export function documentFileUrl(documentId: string, download = false): string {
  return `${API_BASE}/documents/${documentId}/content${download ? '?download=true' : ''}`
}

// --- 长期记忆 ---

export function getMemory(): Promise<MemoryProfile> {
  return request<MemoryProfile>('/memory')
}

export function setPreference(key: string, value: string): Promise<MemoryProfile> {
  return request<MemoryProfile>(`/memory/preferences/${encodeURIComponent(key)}`, {
    method: 'PUT',
    body: JSON.stringify({ value }),
  })
}

export function deletePreference(key: string): Promise<MemoryProfile> {
  return request<MemoryProfile>(`/memory/preferences/${encodeURIComponent(key)}`, {
    method: 'DELETE',
  })
}

export function addMemory(kind: string, content: string): Promise<MemoryRecord> {
  return request<MemoryRecord>('/memory/memories', {
    method: 'POST',
    body: JSON.stringify({ kind, content }),
  })
}

export async function deleteMemory(memoryId: number): Promise<void> {
  const response = await fetch(`${API_BASE}/memory/memories/${memoryId}`, { method: 'DELETE' })
  if (!response.ok) {
    throw await toApiError(response)
  }
}
