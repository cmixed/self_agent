/**
 * 登录态与成员管理客户端。
 *
 * - 令牌存 localStorage，所有请求自动带 Authorization: Bearer。
 * - 401 时清除令牌并通知外壳回到登录页（避免各处重复处理）。
 * - 不依赖 api.ts，避免循环引用（API_BASE 在此重复定义）。
 */

const API_BASE = '/api'
const TOKEN_KEY = 'kb-agent.auth.token'
const USER_KEY = 'kb-agent.auth.user'

export interface Member {
  user_id: string
  username: string | null
  display_name: string
  email: string | null
  role: string
  status: string
  created_at: string
  last_login_at: string | null
}

export interface LoginResponse {
  token: string
  expires_at: string
  user: Member
}

export interface ResetRequestResponse {
  sent: boolean
  email_hint: string | null
  message: string
}

let unauthorizedHandler: (() => void) | null = null

/** 外壳注册：令牌失效时回到登录页。 */
export function onUnauthorized(handler: (() => void) | null) {
  unauthorizedHandler = handler
}

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function getCachedUser(): Member | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as Member) : null
  } catch {
    return null
  }
}

function persist(token: string, user: Member) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    // localStorage 不可用（隐私模式）时退化为内存态：本次会话仍可用
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  } catch {
    // 忽略
  }
}

async function toError(response: Response): Promise<Error> {
  let detail = `请求失败（HTTP ${response.status}）`
  try {
    const body = (await response.json()) as { detail?: string; error?: string }
    detail = body.detail || body.error || detail
  } catch {
    // 非 JSON 错误页，保留默认文案
  }
  const error = new Error(detail)
  ;(error as Error & { status?: number }).status = response.status
  return error
}

/** 统一请求：自动附加令牌，401 时清理会话。 */
export async function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers)
  const token = getToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const response = await fetch(input, { ...init, headers })
  if (response.status === 401 && token) {
    clearSession()
    unauthorizedHandler?.()
  }
  return response
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authFetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    throw await toError(response)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

// ---------- 登录 ----------

export async function login(account: string, password: string): Promise<LoginResponse> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account, password }),
  })
  if (!response.ok) {
    throw await toError(response)
  }
  const data = (await response.json()) as LoginResponse
  persist(data.token, data.user)
  return data
}

export async function logout(): Promise<void> {
  try {
    await authFetch(`${API_BASE}/auth/logout`, { method: 'POST' })
  } catch {
    // 退出失败也要清本地态
  }
  clearSession()
}

export async function fetchMe(): Promise<Member> {
  const user = await requestJson<Member>('/auth/me')
  persist(getToken(), user)
  return user
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await requestJson<void>('/auth/password', {
    method: 'POST',
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  })
}

export async function requestPasswordReset(account: string): Promise<ResetRequestResponse> {
  const response = await fetch(`${API_BASE}/auth/reset/request`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account }),
  })
  if (!response.ok) {
    throw await toError(response)
  }
  return (await response.json()) as ResetRequestResponse
}

export async function confirmPasswordReset(
  account: string,
  code: string,
  newPassword: string,
): Promise<void> {
  const response = await fetch(`${API_BASE}/auth/reset/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account, code, new_password: newPassword }),
  })
  if (!response.ok) {
    throw await toError(response)
  }
}

// ---------- 成员管理 ----------

export async function listMembers(): Promise<Member[]> {
  const data = await requestJson<{ items: Member[] }>('/members')
  return data.items
}

export async function createMember(payload: {
  username: string
  display_name: string
  email?: string
  password: string
  role: string
}): Promise<Member> {
  return requestJson<Member>('/members', { method: 'POST', body: JSON.stringify(payload) })
}

export async function updateMember(
  userId: string,
  payload: { display_name?: string; email?: string; role?: string; status?: string },
): Promise<Member> {
  return requestJson<Member>(`/members/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function resetMemberPassword(userId: string, newPassword: string): Promise<void> {
  await requestJson<void>(`/members/${encodeURIComponent(userId)}/password`, {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword }),
  })
}

// ---------- API 密钥（对外接口） ----------

export interface ApiKey {
  key_id: string
  user_id: string
  label: string
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export async function listApiKeys(userId?: string): Promise<ApiKey[]> {
  const suffix = userId ? `?user_id=${encodeURIComponent(userId)}` : ''
  const data = await requestJson<{ items: ApiKey[] }>(`/api-keys${suffix}`)
  return data.items
}

export async function createApiKey(
  label: string,
  userId?: string,
): Promise<ApiKey & { key: string }> {
  return requestJson<ApiKey & { key: string }>('/api-keys', {
    method: 'POST',
    body: JSON.stringify({ label, user_id: userId }),
  })
}

export async function revokeApiKey(keyId: string): Promise<void> {
  await requestJson<void>(`/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' })
}
