/** 展示层格式化工具（由后端已有字段推导，不新增数据来源） */

import type { TokenUsage } from '../types/api'

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

/** 两位数补零（日期 / 时间格式化用）。 */
function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

/**
 * ISO 时间 -> 浏览器本地时区的可读写法（`YYYY-MM-DD HH:mm:ss`）。
 *
 * 后端统一存 UTC（`+00:00`），必须经过 `Date` 转换成本地时间；
 * 直接截掉 `Z` / `+00:00` 会把 UTC 当成本地时间，导致时区偏移
 * （例如 UTC+8 下显示的创建时间比实际早 8 小时）。
 */
export function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const day = `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
  const time = `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`
  return `${day} ${time}`
}

export type DocumentKind = 'pdf' | 'markdown' | 'text' | 'unknown'

/** token 数 -> 1.2k / 12k / 1.3M（数值越大保留的小数越少） */
export function formatTokens(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (!Number.isFinite(value) || value < 0) return '—'
  if (value < 1000) return String(Math.round(value))
  if (value < 10_000) return `${(value / 1000).toFixed(1)}k`
  if (value < 1_000_000) return `${Math.round(value / 1000)}k`
  return `${(value / 1_000_000).toFixed(1)}M`
}

/** 输出速度（completion_tokens / 秒） */
export function formatTokenRate(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (!Number.isFinite(value) || value <= 0) return '—'
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} tok/s`
}

/** 缓存命中率（0–1）；上游未上报缓存时返回 null */
export function cacheHitRate(usage: TokenUsage | null | undefined): number | null {
  if (!usage || !usage.cache_reported || usage.prompt_tokens <= 0) return null
  return usage.cache_hit_tokens / usage.prompt_tokens
}

/** 按扩展名判断文档类型（用于列表图标） */
export function documentKind(filename: string): DocumentKind {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.pdf')) return 'pdf'
  if (lower.endsWith('.md') || lower.endsWith('.markdown')) return 'markdown'
  if (lower.endsWith('.txt')) return 'text'
  return 'unknown'
}
