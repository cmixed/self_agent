/**
 * 顶栏任务胶囊的可调参数（设置页维护，纯 localStorage）。
 *
 * 与 `utils/runningTasks.ts` 的分工：那里是展示/排序逻辑，这里只负责
 * 「用户偏好的数值 + 校验 + 持久化」。
 */

export const PILL_SETTINGS_STORAGE_KEY = 'agent.pillSettings'

export interface PillSettings {
  /** 会话内非失败待查看最多保留几条（失败任务不受限制）。 */
  pendingLimit: number
  /** 刷新页面时只恢复最近多少小时内结束的任务。 */
  restoreWindowHours: number
  /** 刷新页面时最多恢复几条未查看的完成态胶囊。 */
  restoreLimit: number
}

export interface PillSettingRange {
  min: number
  max: number
  fallback: number
}

/** 每项的取值范围与默认值（默认值同时也是「恢复默认」的目标）。 */
export const PILL_SETTING_RANGES = {
  pendingLimit: { min: 1, max: 20, fallback: 5 },
  restoreWindowHours: { min: 1, max: 168, fallback: 24 },
  restoreLimit: { min: 1, max: 10, fallback: 3 },
} as const

export const DEFAULT_PILL_SETTINGS: PillSettings = {
  pendingLimit: PILL_SETTING_RANGES.pendingLimit.fallback,
  restoreWindowHours: PILL_SETTING_RANGES.restoreWindowHours.fallback,
  restoreLimit: PILL_SETTING_RANGES.restoreLimit.fallback,
}

type ReadableStorage = { getItem: (key: string) => string | null }
type WritableStorage = Pick<Storage, 'setItem'>

function defaultStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    // 隐私模式等场景下 localStorage 不可用
    return null
  }
}

function clampInt(value: unknown, range: PillSettingRange): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return range.fallback
  return Math.min(range.max, Math.max(range.min, Math.round(parsed)))
}

/** 把任意输入夹取为合法设置（缺省 / 非法项回退默认值）。 */
export function clampPillSettings(raw: unknown): PillSettings {
  const data = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
  return {
    pendingLimit: clampInt(data.pendingLimit, PILL_SETTING_RANGES.pendingLimit),
    restoreWindowHours: clampInt(data.restoreWindowHours, PILL_SETTING_RANGES.restoreWindowHours),
    restoreLimit: clampInt(data.restoreLimit, PILL_SETTING_RANGES.restoreLimit),
  }
}

/** 读取胶囊设置；缺失 / 损坏时回退默认值。 */
export function readPillSettings(storage: ReadableStorage | null = defaultStorage()): PillSettings {
  try {
    const raw = storage?.getItem(PILL_SETTINGS_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_PILL_SETTINGS }
    return clampPillSettings(JSON.parse(raw))
  } catch {
    return { ...DEFAULT_PILL_SETTINGS }
  }
}

/** 写入胶囊设置（先夹取，避免把越界值存进去）。 */
export function writePillSettings(
  settings: PillSettings,
  storage: WritableStorage | null = defaultStorage(),
): PillSettings {
  const next = clampPillSettings(settings)
  try {
    storage?.setItem(PILL_SETTINGS_STORAGE_KEY, JSON.stringify(next))
  } catch {
    // 忽略写入失败：本次会话内仍生效
  }
  return next
}
