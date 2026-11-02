import type {
  ApiErrorBody,
  ChatMessage,
  CategoryInfo,
  CategoryListResponse,
  ChatResponse,
  DocumentInfo,
  HealthResponse,
  KnowledgeImportPreview,
  KnowledgeImportResult,
  MemoryImportPreview,
  MemoryImportResult,
  MemoryProfile,
  MemoryRecord,
  BackupImportPreview,
  BackupImportResult,
  PresetImportPreview,
  PresetImportResult,
  PresetInfo,
  PresetListResponse,
  ModelListResponse,
  OutputMode,
  ProviderInfo,
  ProviderListResponse,
  ProviderProbeResponse,
  RetrievalMode,
  SettingsResponse,
  SkillGenerateResponse,
  SkillImportPreview,
  SkillInfo,
  SkillListResponse,
  SkillResourceInfo,
  SkillResourceListResponse,
  TaskScope,
  TaskDepth,
  TaskDetail,
  TaskEmailResponse,
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

/** 统一导入流程：上传文件并解析预览（不落库）。 */
async function uploadForPreview<T>(path: string, file: File): Promise<T> {
  const body = new FormData()
  body.append('file', file)
  // 不要手动设置 Content-Type：浏览器需要自己生成 multipart boundary
  const response = await fetch(`${API_BASE}${path}`, { method: 'POST', body })
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as T
}

/** 统一导出流程：下载后端打包好的文件，并保留响应中的文件名。 */
async function downloadPackage(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw await toApiError(response)
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^";]+)"?/.exec(disposition)
  return {
    blob: await response.blob(),
    filename: match?.[1] ?? 'export.bin',
  }
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

export function listTasks(
  limit = 20,
  status?: string,
  outputMode?: OutputMode,
): Promise<TaskListResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (status) params.set('status', status)
  if (outputMode) params.set('output_mode', outputMode)
  return request<TaskListResponse>(`/tasks?${params.toString()}`)
}

export function getTask(taskId: string): Promise<TaskDetail> {
  return request<TaskDetail>(`/tasks/${taskId}`)
}

export function getTaskState(taskId: string): Promise<TaskState> {
  return request<TaskState>(`/tasks/${taskId}/state`)
}

/** 把已完成任务的正文发送到邮箱（纯文本正文 + Markdown 附件）。 */
export function sendTaskEmail(taskId: string, to: string): Promise<TaskEmailResponse> {
  return request<TaskEmailResponse>(`/tasks/${encodeURIComponent(taskId)}/email`, {
    method: 'POST',
    body: JSON.stringify({ to }),
  })
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
  depth: TaskDepth = 'auto',
  useSkills = false,
  retrievalMode: RetrievalMode = 'all',
  outputMode: OutputMode = 'generate',
  verbatimDocumentId?: string | null,
): Promise<void> {
  const hasScope =
    retrievalMode === 'selected' &&
    Boolean(scope && (scope.category_ids.length || scope.document_ids.length))
  return streamSse(
    '/tasks/stream',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // retrieval_mode=all 时不传 scope（后端按整个知识库处理）；
      // none 表示本次完全不检索；depth=auto 由后端确定性路由决定。
      // verbatim 模式不进入 Agent 生成流程，verbatim_document_id 为空表示自动选择。
      body: JSON.stringify({
        query,
        depth,
        use_skills: useSkills,
        retrieval_mode: retrievalMode,
        output_mode: outputMode,
        ...(outputMode === 'verbatim' && verbatimDocumentId
          ? { verbatim_document_id: verbatimDocumentId }
          : {}),
        ...(hasScope ? { scope } : {}),
      }),
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

/**
 * 观察一个已有任务的事件流（AGENTS.md §18/§19）。
 *
 * 任务执行与浏览器连接解耦：刷新页面后重新订阅即可从服务端事件缓冲区完整
 * 回放，再跟随实时事件；断开只会取消订阅，不会取消任务本身。
 */
export async function streamObserve(
  taskId: string,
  onEvent: (event: TaskEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse(
    `/tasks/${encodeURIComponent(taskId)}/stream`,
    { method: 'GET' },
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
  // headers 可能是 HeadersInit（数组/Headers/对象），用 Headers 归一化后再覆盖
  const headers = new Headers(init.headers)
  headers.set('Accept', 'text/event-stream')
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
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

/** 上传并索引文档（multipart：不要手动设置 Content-Type，交给浏览器带 boundary）。
 *
 * 用 XHR 而不是 fetch：只有 XHR 能拿到上传进度（大 PDF 时前端需要真实反馈）。
 */
export function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<DocumentInfo> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}/documents/upload`)
    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)))
        }
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as DocumentInfo)
        } catch {
          reject(new ApiError(xhr.status, { error: 'invalid_response', error_type: 'unknown' }))
        }
        return
      }
      let body: ApiErrorBody = { error: 'request_failed', error_type: 'unknown' }
      try {
        body = JSON.parse(xhr.responseText) as ApiErrorBody
      } catch {
        // 后端可能返回非 JSON 错误页，忽略解析失败
      }
      reject(new ApiError(xhr.status, body))
    }
    xhr.onerror = () =>
      reject(
        new ApiError(0, {
          error: 'network_error',
          detail: '无法连接后端，请确认 FastAPI 已启动',
          error_type: 'network_error',
        }),
      )
    xhr.onabort = () =>
      reject(new ApiError(0, { error: 'aborted', detail: '上传已取消', error_type: 'aborted' }))
    xhr.send(form)
  })
}

/** 知识库文档原文件的访问地址（download=true 时为附件下载，否则内联预览）。 */
export function documentFileUrl(documentId: string, download = false): string {
  return `${API_BASE}/documents/${documentId}/content${download ? '?download=true' : ''}`
}

// --- 知识库导入 / 导出 ---

export function exportKnowledgeBase(): Promise<{ blob: Blob; filename: string }> {
  return downloadPackage('/documents/export')
}

export function previewKnowledgeImport(file: File): Promise<KnowledgeImportPreview> {
  return uploadForPreview<KnowledgeImportPreview>('/documents/import/preview', file)
}

export function confirmKnowledgeImport(token: string): Promise<KnowledgeImportResult> {
  return request<KnowledgeImportResult>('/documents/import', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}

// --- 技能 ---

export function listSkills(): Promise<SkillListResponse> {
  return request<SkillListResponse>('/skills')
}

export function createSkill(payload: {
  name: string
  description: string
  content: string
  source_filename?: string | null
}): Promise<SkillInfo> {
  return request<SkillInfo>('/skills', { method: 'POST', body: JSON.stringify(payload) })
}

/** 从知识库文档生成技能草稿（不落库，审核后再调用 createSkill 保存）。 */
export function generateSkill(payload: {
  document_ids: string[]
  hint?: string
}): Promise<SkillGenerateResponse> {
  return request<SkillGenerateResponse>('/skills/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
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

export function listSkillResources(skillId: string): Promise<SkillResourceListResponse> {
  return request<SkillResourceListResponse>(`/skills/${encodeURIComponent(skillId)}/resources`)
}

export function createSkillResource(
  skillId: string,
  payload: { name: string; content: string },
): Promise<SkillResourceInfo> {
  return request<SkillResourceInfo>(`/skills/${encodeURIComponent(skillId)}/resources`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateSkillResource(
  skillId: string,
  resourceId: string,
  payload: Partial<{ name: string; content: string }>,
): Promise<SkillResourceInfo> {
  return request<SkillResourceInfo>(
    `/skills/${encodeURIComponent(skillId)}/resources/${encodeURIComponent(resourceId)}`,
    { method: 'PUT', body: JSON.stringify(payload) },
  )
}

export async function deleteSkillResource(skillId: string, resourceId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE}/skills/${encodeURIComponent(skillId)}/resources/${encodeURIComponent(resourceId)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) {
    throw await toApiError(response)
  }
}

// --- 技能包导入 / 导出（标准 SKILL.md 目录）---

/** 上传 zip 技能包并解析预览（不落盘）。 */
export async function previewSkillImport(file: File): Promise<SkillImportPreview> {
  const body = new FormData()
  body.append('file', file)
  // 注意：不要设置 Content-Type，浏览器需要自己带 multipart boundary
  const response = await fetch(`${API_BASE}/skills/import/preview`, { method: 'POST', body })
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as SkillImportPreview
}

/** 确认导入（预览 token 一次性使用）。 */
export function confirmSkillImport(token: string): Promise<SkillInfo> {
  return request<SkillInfo>('/skills/import', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}

/** 导出标准技能包（zip）。 */
export async function exportSkillPackage(skillId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/skills/${encodeURIComponent(skillId)}/export`)
  if (!response.ok) {
    throw await toApiError(response)
  }
  return await response.blob()
}

/** 导出全部技能（zip 集合：每项为标准 SKILL.md 目录）。 */
export function exportSkillsCollection(): Promise<{ blob: Blob; filename: string }> {
  return downloadPackage('/skills/export')
}

// --- 预设任务 ---

export function listPresets(outputMode?: OutputMode): Promise<PresetListResponse> {
  const query = outputMode ? `?output_mode=${outputMode}` : ''
  return request<PresetListResponse>(`/presets${query}`)
}

export function createPreset(payload: {
  title: string
  description: string
  query: string
  output_mode?: OutputMode
  scope?: TaskScope | null
  auto_run?: boolean
}): Promise<PresetInfo> {
  return request<PresetInfo>('/presets', { method: 'POST', body: JSON.stringify(payload) })
}

export function reorderPresets(
  presetIds: string[],
  outputMode: OutputMode = 'generate',
): Promise<PresetListResponse> {
  return request<PresetListResponse>('/presets/order', {
    method: 'PUT',
    body: JSON.stringify({ preset_ids: presetIds, output_mode: outputMode }),
  })
}

export function updatePreset(
  presetId: string,
  payload: Partial<{
    title: string
    description: string
    query: string
    output_mode: OutputMode
    scope: TaskScope | null
    auto_run: boolean
  }>,
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

// --- 预设导入 / 导出 ---

export function exportPresets(): Promise<{ blob: Blob; filename: string }> {
  return downloadPackage('/presets/export')
}

export function previewPresetImport(file: File): Promise<PresetImportPreview> {
  return uploadForPreview<PresetImportPreview>('/presets/import/preview', file)
}

export function confirmPresetImport(token: string): Promise<PresetImportResult> {
  return request<PresetImportResult>('/presets/import', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}

// --- 模型服务（自定义 Provider）---

export function listProviders(): Promise<ProviderListResponse> {
  return request<ProviderListResponse>('/providers')
}

export function createProvider(payload: {
  /** 留空则由后端默认使用模型名 */
  label?: string
  base_url: string
  model: string
  api_key?: string
  api_key_env?: string
  requires_api_key: boolean
  is_local: boolean
  timeout_seconds?: number
  max_retries?: number
  flavor?: string
  disable_thinking?: boolean
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
    flavor: string
    disable_thinking: boolean
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
export function discoverModels(baseUrl: string, providerId?: string): Promise<ModelListResponse> {
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

// --- 长期记忆导入 / 导出 ---

export function exportMemory(): Promise<{ blob: Blob; filename: string }> {
  return downloadPackage('/memory/export')
}

export function previewMemoryImport(file: File): Promise<MemoryImportPreview> {
  return uploadForPreview<MemoryImportPreview>('/memory/import/preview', file)
}

export function confirmMemoryImport(token: string): Promise<MemoryImportResult> {
  return request<MemoryImportResult>('/memory/import', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}

// --- 系统级一键备份 / 恢复 ---

export function exportBackup(): Promise<{ blob: Blob; filename: string }> {
  return downloadPackage('/backup/export')
}

export function previewBackupImport(file: File): Promise<BackupImportPreview> {
  return uploadForPreview<BackupImportPreview>('/backup/import/preview', file)
}

export function confirmBackupImport(token: string): Promise<BackupImportResult> {
  return request<BackupImportResult>('/backup/import', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}
