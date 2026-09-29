/** 展示层格式化工具（由后端已有字段推导，不新增数据来源） */

/** 秒 -> 人类可读时长 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return rest === 0 ? `${minutes}m` : `${minutes}m ${rest}s`
}

/** 由 created_at / finished_at 推导任务耗时（秒） */
export function taskDurationSeconds(
  createdAt?: string | null,
  finishedAt?: string | null,
): number | null {
  if (!createdAt || !finishedAt) return null
  const start = Date.parse(createdAt)
  const end = Date.parse(finishedAt)
  if (Number.isNaN(start) || Number.isNaN(end)) return null
  return Math.max(0, (end - start) / 1000)
}

/** ISO 时间 -> 便于阅读的本地写法 */
export function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  return value.replace('T', ' ').replace('+00:00', '').replace('Z', '')
}

export type DocumentKind = 'pdf' | 'markdown' | 'text' | 'unknown'

/** 按扩展名判断文档类型（用于列表图标） */
export function documentKind(filename: string): DocumentKind {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.pdf')) return 'pdf'
  if (lower.endsWith('.md') || lower.endsWith('.markdown')) return 'markdown'
  if (lower.endsWith('.txt')) return 'text'
  return 'unknown'
}
