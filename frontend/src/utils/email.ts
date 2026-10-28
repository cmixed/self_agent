/** 邮箱地址的纯函数工具（校验 / 归一化 / 脱敏 / 记住上次收件人）。 */

export const EMAIL_RECIPIENT_STORAGE_KEY = 'agent.email.recipient'

// 与后端保持同一套保守规则：常见 ASCII 地址，拒绝换行（邮件头注入）。
const EMAIL_RE =
  /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/

function defaultStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    // 隐私模式 / 禁用 localStorage 时不要影响发送主流程
    return null
  }
}

/** 去掉首尾空白并把域名转小写（本地部分保持原样）。 */
export function normalizeRecipient(value: string): string {
  const candidate = (value ?? '').trim()
  const at = candidate.lastIndexOf('@')
  if (at <= 0) return candidate
  return `${candidate.slice(0, at)}@${candidate.slice(at + 1).toLowerCase()}`
}

export function isValidEmail(value: string): boolean {
  const candidate = normalizeRecipient(value)
  if (candidate.length < 3 || candidate.length > 254) return false
  if (candidate.includes('\r') || candidate.includes('\n')) return false
  const at = candidate.lastIndexOf('@')
  if (at <= 0 || at === candidate.length - 1) return false
  if (at > 64) return false
  return EMAIL_RE.test(candidate)
}

/** 前端回显用的脱敏地址（后端响应已脱敏，这里用于本地提示）。 */
export function maskEmail(value: string): string {
  const candidate = normalizeRecipient(value)
  const at = candidate.lastIndexOf('@')
  if (at <= 0) return '***'
  return `${candidate.slice(0, 1)}***@${candidate.slice(at + 1)}`
}

export function readLastRecipient(storage: Storage | null = defaultStorage()): string {
  if (!storage) return ''
  try {
    const saved = storage.getItem(EMAIL_RECIPIENT_STORAGE_KEY) ?? ''
    return isValidEmail(saved) ? normalizeRecipient(saved) : ''
  } catch {
    return ''
  }
}

export function saveLastRecipient(value: string, storage: Storage | null = defaultStorage()): void {
  if (!storage) return
  const candidate = normalizeRecipient(value)
  if (!isValidEmail(candidate)) return
  try {
    storage.setItem(EMAIL_RECIPIENT_STORAGE_KEY, candidate)
  } catch {
    // 存不下不影响发送：用户下次重新填写即可
  }
}
