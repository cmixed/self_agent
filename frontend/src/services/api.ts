import type {
  ApiErrorBody,
  ChatMessage,
  CategoryInfo,
  CategoryListResponse,
  ChatResponse,
  DocumentInfo,
  HealthResponse,
  MemoryProfile,
  MemoryRecord,
  PresetInfo,
  PresetListResponse,
  ModelListResponse,
  ProviderInfo,
  ProviderListResponse,
  ProviderProbeResponse,
  SettingsResponse,
  SkillInfo,
  TaskScope,
  SkillListResponse,
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
  scope?: TaskScope | null,
): Promise<void> {
  const hasScope = Boolean(scope && (scope.category_ids.length || scope.document_ids.length))
  return streamSse(
    '/tasks/stream',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // scope 缺省 = 全部知识库（后端不解析、不加过滤）
      body: JSON.stringify(hasScope ? { query, scope } : { query }),
    },
    onEvent,
    signal,
  )
}

/** 从断点继续生成（同一任务，已完成的步骤不重跑）。 */
export async function streamResume(
  taskId: string,
  onEvent: (event: TaskEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse(
    `/tasks/${encodeURIComponent(taskId)}/resume`,
    { method: 'POST' },
    onEvent,
    signal,
  )
}

/** 用同一任务内容重新生成（新任务 id，原任务记录保留）。 */
export async function streamRerun(
  taskId: string,
  onEvent: (event: TaskEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse(
    `/tasks/${encodeURIComponent(taskId)}/rerun`,
    { method: 'POST' },
    onEvent,
    signal,
  )
}

/** 消费 SSE 任务流（fetch + ReadableStream：EventSource 不支持 POST）。 */
async function streamSse(
  path: string,
  init: RequestInit,
  onEvent: (event: TaskEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: 'text/event-stream', ...(init.headers ?? {}) },
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

// --- 技能 ---

export function listSkills(): Promise<SkillListResponse> {
  return request<SkillListResponse>('/skills')
}

export function createSkill(payload: {
  name: string
  description: string
  content: string
}): Promise<SkillInfo> {
  return request<SkillInfo>('/skills', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateSkill(
  skillId: string,
  payload: Partial<{ name: string; description: string; content: string; enabled: boolean }>,
): Promise<SkillInfo> {
  return request<SkillInfo>(`/skills/${encodeURIComponent(skillId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteSkill(skillId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/skills/${encodeURIComponent(skillId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
}

// --- 预设任务 ---

export function listPresets(): Promise<PresetListResponse> {
  return request<PresetListResponse>('/presets')
}

export function createPreset(payload: {
  title: string
  description: string
  query: string
}): Promise<PresetInfo> {
  return request<PresetInfo>('/presets', { method: 'POST', body: JSON.stringify(payload) })
}

export function updatePreset(
  presetId: string,
  payload: Partial<{ title: string; description: string; query: string }>,
): Promise<PresetInfo> {
  return request<PresetInfo>(`/presets/${encodeURIComponent(presetId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deletePreset(presetId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/presets/${encodeURIComponent(presetId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
}

// --- 模型服务（自定义 Provider）---

export function listProviders(): Promise<ProviderListResponse> {
  return request<ProviderListResponse>('/providers')
}

export function createProvider(payload: {
  label: string
  base_url: string
  model: string
  api_key?: string
  api_key_env?: string
  requires_api_key: boolean
  is_local: boolean
  timeout_seconds?: number
  max_retries?: number
}): Promise<ProviderInfo> {
  return request<ProviderInfo>('/providers', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateProvider(
  providerId: string,
  payload: Partial<{
    label: string
    base_url: string
    model: string
    api_key: string
    api_key_env: string
    requires_api_key: boolean
    is_local: boolean
    timeout_seconds: number
    max_retries: number
  }>,
): Promise<ProviderInfo> {
  return request<ProviderInfo>(`/providers/${encodeURIComponent(providerId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteProvider(providerId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/providers/${encodeURIComponent(providerId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
}

/** 发现端点可用模型（后端代理，避免跨域）。 */
export function discoverModels(
  baseUrl: string,
  providerId?: string,
): Promise<ModelListResponse> {
  const params = new URLSearchParams({ base_url: baseUrl })
  if (providerId) params.set('provider_id', providerId)
  return request<ModelListResponse>(`/providers/models?${params.toString()}`)
}

/** 测试连接（真实发一条极小请求）。 */
export function testProvider(payload: {
  base_url: string
  model: string
  provider_id?: string
  api_key?: string
  requires_api_key: boolean
  is_local: boolean
  timeout_seconds?: number
}): Promise<ProviderProbeResponse> {
  return request<ProviderProbeResponse>('/providers/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

// --- 知识库类别（多标签组织）---

export function listCategories(): Promise<CategoryListResponse> {
  return request<CategoryListResponse>('/categories')
}

export function createCategory(payload: {
  name: string
  description?: string
}): Promise<CategoryInfo> {
  return request<CategoryInfo>('/categories', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateCategory(
  categoryId: string,
  payload: { name?: string; description?: string },
): Promise<CategoryInfo> {
  return request<CategoryInfo>(`/categories/${encodeURIComponent(categoryId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteCategory(categoryId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/categories/${encodeURIComponent(categoryId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
}

/** 整组替换某文档的类别。 */
export function setDocumentCategories(
  documentId: string,
  categoryIds: string[],
): Promise<{ document_id: string; category_ids: string[] }> {
  return request<{ document_id: string; category_ids: string[] }>(
    `/documents/${encodeURIComponent(documentId)}/categories`,
    { method: 'PUT', body: JSON.stringify({ category_ids: categoryIds }) },
  )
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
