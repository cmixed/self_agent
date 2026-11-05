/** 顶栏任务胶囊（运行中 / 完成待查看）的纯逻辑（便于单测，不依赖 React）。 */

import type { TaskSummary } from '../types/api'

/** 桌面端直接展示的胶囊数量绝对上限（实际数量按顶栏可用宽度自适应）。 */
export const MAX_VISIBLE_CAPSULES = 4

/** 宽度尚未测量时的回退数量。 */
export const DEFAULT_VISIBLE_CAPSULES = 2

/** 单个胶囊的宽度估算（含标题、状态与内边距）。 */
export const CAPSULE_WIDTH = 190
/** 「+N」按钮的宽度估算。 */
export const MORE_BUTTON_WIDTH = 60
/** 胶囊之间的间距估算（与 CSS 保持一致）。 */
export const CAPSULE_GAP = 8

/** 会话内最多同时保留多少条「待查看」胶囊；失败任务不受此限制。 */
export const MAX_PENDING_FINISHED = 5

/** 终态：任务已结束，胶囊转为「完成待查看」常驻。 */
const TERMINAL_STATUSES = ['completed', 'failed', 'cancelled'] as const
export type TerminalStatus = (typeof TERMINAL_STATUSES)[number]
export type TaskPillState = 'running' | TerminalStatus

/** 刷新页面后最多恢复多少条「完成待查看」胶囊（避免翻出很久以前的旧账）。 */
export const MAX_RESTORED_FINISHED = 3

/** 「完成待查看」的恢复窗口：只恢复最近 24 小时内结束的任务。 */
export const FINISHED_RESTORE_WINDOW_MS = 24 * 60 * 60 * 1000

/** 已确认（查看/关闭）的任务 id 存储键，刷新后不再重复弹出。 */
export const ACKNOWLEDGED_STORAGE_KEY = 'agent.finishedTasks.ack'
const MAX_ACKNOWLEDGED = 100

export function isTerminalStatus(status?: string | null): status is TerminalStatus {
  return (TERMINAL_STATUSES as readonly string[]).includes(status ?? '')
}

/** 胶囊状态：运行中 + 三种终态（后端只会有这四种）。 */
export function taskPillState(task: Pick<TaskSummary, 'status'>): TaskPillState {
  return isTerminalStatus(task.status) ? task.status : 'running'
}

/** 终态胶囊上的短标签。 */
export function pillStatusLabel(state: TaskPillState): string {
  switch (state) {
    case 'completed':
      return '已完成'
    case 'failed':
      return '失败'
    case 'cancelled':
      return '已终止'
    default:
      return '执行中'
  }
}

/** 终态排序键：优先 finished_at，缺失时退回 created_at。 */
function finishTime(task: Pick<TaskSummary, 'finished_at' | 'created_at'>): number {
  const value = task.finished_at ?? task.created_at
  const parsed = value ? Date.parse(value) : Number.NaN
  return Number.isNaN(parsed) ? 0 : parsed
}

/** 运行中任务按开始时间排序。 */
function createdTime(task: Pick<TaskSummary, 'created_at'>): number {
  const parsed = task.created_at ? Date.parse(task.created_at) : Number.NaN
  return Number.isNaN(parsed) ? 0 : parsed
}

/**
 * 可见性排序：失败待查看 > 运行中 > 已完成 / 已终止。
 *
 * 优先级只决定「谁先占用有限的位置」，不改变任务本身的执行顺序；
 * 正在观察的任务仍由 sliceTaskPills 强制放在第一个。
 */
function pillRank(task: Pick<TaskSummary, 'status'>): number {
  if (task.status === 'failed') return 0
  if (task.status === 'running') return 1
  return 2
}

/**
 * 合并「运行中 + 完成待查看」为一条胶囊列表。
 *
 * 失败待查看最靠前（红色提醒不能被运行中任务挤掉），其次运行中（按开始时间
 * 倒序），最后是已完成 / 已终止（按结束时间倒序）；同一 task_id 只保留一条。
 */
export function mergeTaskPills(
  running: readonly TaskSummary[],
  finished: readonly TaskSummary[],
): TaskSummary[] {
  const seen = new Set<string>()
  const tasks: TaskSummary[] = []
  for (const task of [...running, ...finished]) {
    if (seen.has(task.task_id)) continue
    seen.add(task.task_id)
    tasks.push(task)
  }
  return tasks.sort((a, b) => {
    const rank = pillRank(a) - pillRank(b)
    if (rank !== 0) return rank
    if (pillRank(a) === 1) return createdTime(b) - createdTime(a)
    return finishTime(b) - finishTime(a)
  })
}

/**
 * 按顶栏实际可用宽度计算能直接展示几个胶囊。
 *
 * - 全部放得下时返回任务总数（不出现「+N」）；
 * - 放不下时预留「+N」的位置，最多 `max` 个；
 * - 宽度未知（首帧 / 不支持测量）时回退到 `fallback`；
 * - 即使一个都放不下也返回 1，由 CSS 收缩兜底，保证任务可访问。
 */
export function visibleCapsuleCount(
  total: number,
  availableWidth: number,
  options: {
    pillWidth?: number
    moreWidth?: number
    gap?: number
    max?: number
    fallback?: number
  } = {},
): number {
  if (total <= 0) return 0
  const pillWidth = options.pillWidth ?? CAPSULE_WIDTH
  const moreWidth = options.moreWidth ?? MORE_BUTTON_WIDTH
  const gap = options.gap ?? CAPSULE_GAP
  const max = Math.max(1, options.max ?? MAX_VISIBLE_CAPSULES)
  const fallback = Math.max(1, Math.min(total, options.fallback ?? DEFAULT_VISIBLE_CAPSULES))
  if (!Number.isFinite(availableWidth) || availableWidth <= 0) return fallback

  let best = 0
  for (let count = 1; count <= Math.min(total, max); count += 1) {
    const rowWidth = count * pillWidth + (count - 1) * gap
    const overflow = total - count
    const needed = rowWidth + (overflow > 0 ? gap + moreWidth : 0)
    if (needed > availableWidth) break
    best = count
  }
  return best > 0 ? best : 1
}

/**
 * 会话内待查看数量兜底（E）：非失败任务只保留最新 `limit` 条。
 *
 * 失败任务永不自动丢弃，避免红色提醒被悄悄吞掉；被丢弃的条目由调用方
 * 标记为已查看（任务本身仍在历史里）。
 */
export function splitPendingFinished(
  tasks: readonly TaskSummary[],
  limit = MAX_PENDING_FINISHED,
): { kept: TaskSummary[]; dropped: TaskSummary[] } {
  const kept: TaskSummary[] = []
  const dropped: TaskSummary[] = []
  let others = 0
  for (const task of tasks) {
    if (task.status === 'failed') {
      kept.push(task)
      continue
    }
    if (others < limit) {
      kept.push(task)
      others += 1
    } else {
      dropped.push(task)
    }
  }
  return { kept, dropped }
}

export interface TaskPillGroup {
  key: 'pending' | 'running'
  label: string
  tasks: TaskSummary[]
}

export interface TaskPillCounts {
  running: number
  pending: number
  failed: number
}

/** 胶囊集合的构成统计（待查看包含失败）。 */
export function pillCounts(tasks: readonly TaskSummary[]): TaskPillCounts {
  let running = 0
  let failed = 0
  for (const task of tasks) {
    if (task.status === 'running') running += 1
    else if (task.status === 'failed') failed += 1
  }
  return { running, pending: tasks.length - running, failed }
}

/** 「+N」的悬停说明：让用户知道被折叠的任务里有多少在跑、多少待查看。 */
export function overflowSummary(tasks: readonly TaskSummary[]): string {
  const { running, pending, failed } = pillCounts(tasks)
  const parts: string[] = []
  if (running > 0) parts.push(`${running} 个执行中`)
  if (pending > 0) {
    parts.push(`${pending} 个待查看${failed > 0 ? `（含 ${failed} 个失败）` : ''}`)
  }
  return `另有 ${tasks.length} 个任务未显示：${parts.join('、')}`
}

/**
 * 下拉菜单分组：待查看（失败置顶） → 执行中。
 *
 * 只在确实有任务被折叠时使用；只有一组时调用方应直接平铺，避免多余标题。
 */
export function groupTaskPills(tasks: readonly TaskSummary[]): TaskPillGroup[] {
  const pending = tasks
    .filter((task) => task.status !== 'running')
    .sort((a, b) => pillRank(a) - pillRank(b) || finishTime(b) - finishTime(a))
  const running = tasks
    .filter((task) => task.status === 'running')
    .sort((a, b) => createdTime(b) - createdTime(a))

  const groups: TaskPillGroup[] = []
  if (pending.length > 0) {
    groups.push({ key: 'pending', label: `待查看（${pending.length}）`, tasks: pending })
  }
  if (running.length > 0) {
    groups.push({ key: 'running', label: `执行中（${running.length}）`, tasks: running })
  }
  return groups
}

/**
 * 计算「完成待查看」列表：保留已有条目，并补上服务端新出现的终态任务。
 *
 * - `acknowledged`：用户已查看/关闭过的任务，永不重复出现；
 * - `skipIds`：正在工作台观察的任务（已经看得到结果，不再弹胶囊）；
 * - 只接受 `windowMs` 内结束的任务，避免启动时把陈年旧账翻出来；
 * - `limit` 仅用于启动恢复，运行期间新完成的任务不丢。
 */
export function collectFinishedTasks(options: {
  tasks: readonly TaskSummary[]
  current: readonly TaskSummary[]
  acknowledged: ReadonlySet<string>
  skipIds?: ReadonlySet<string>
  now?: number
  windowMs?: number
  limit?: number
}): TaskSummary[] {
  const now = options.now ?? Date.now()
  const windowMs = options.windowMs ?? FINISHED_RESTORE_WINDOW_MS
  const skip = options.skipIds ?? new Set<string>()
  const latestById = new Map(options.tasks.map((task) => [task.task_id, task]))

  const keep = options.current
    .filter((task) => {
      if (!isTerminalStatus(task.status)) return false
      if (options.acknowledged.has(task.task_id) || skip.has(task.task_id)) return false
      // 同一条任务被续跑（复用 task_id）后重新变成 running：撤掉旧的完成态
      const latest = latestById.get(task.task_id)
      return !latest || isTerminalStatus(latest.status)
    })
    // 用服务端最新记录刷新（失败原因 / finished_at 可能已更新）
    .map((task) => latestById.get(task.task_id) ?? task)
  const known = new Set(keep.map((task) => task.task_id))

  for (const task of options.tasks) {
    if (!isTerminalStatus(task.status)) continue
    if (options.acknowledged.has(task.task_id) || skip.has(task.task_id)) continue
    if (known.has(task.task_id)) continue
    const finished = task.finished_at ? Date.parse(task.finished_at) : Number.NaN
    if (Number.isNaN(finished)) continue
    if (now - finished > windowMs) continue
    known.add(task.task_id)
    keep.push(task)
  }

  keep.sort((a, b) => finishTime(b) - finishTime(a))
  return options.limit && options.limit > 0 ? keep.slice(0, options.limit) : keep
}

type ReadableStorage = { getItem: (key: string) => string | null }

function defaultStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    // 隐私模式等场景下 localStorage 不可用
    return null
  }
}

/** 读取「已确认」任务 id（损坏 / 不可用时按空集合处理）。 */
export function loadAcknowledgedTasks(
  storage: ReadableStorage | null = defaultStorage(),
): Set<string> {
  try {
    const raw = storage?.getItem(ACKNOWLEDGED_STORAGE_KEY)
    if (!raw) return new Set()
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return new Set()
    return new Set(parsed.filter((id): id is string => typeof id === 'string' && id.length > 0))
  } catch {
    return new Set()
  }
}

/** 持久化「已确认」任务 id（只保留最近 100 条，避免无限增长）。 */
export function saveAcknowledgedTasks(
  ids: ReadonlySet<string>,
  storage: Pick<Storage, 'setItem'> | null = defaultStorage(),
): void {
  try {
    storage?.setItem(ACKNOWLEDGED_STORAGE_KEY, JSON.stringify([...ids].slice(-MAX_ACKNOWLEDGED)))
  } catch {
    // 忽略写入失败：本次会话内仍生效
  }
}

/** §19 事件名 -> 阶段文案（有 message 时优先用 message）。 */
const STAGE_LABELS: Record<string, string> = {
  task_started: '准备中',
  task_resumed: '继续生成',
  planner_started: '规划任务',
  planner_completed: '规划完成',
  researcher_started: '检索资料',
  researcher_completed: '检索完成',
  skills_started: '执行技能',
  skills_completed: '技能完成',
  outline_started: '生成大纲',
  outline_completed: '大纲完成',
  writer_started: '撰写章节',
  writer_completed: '章节完成',
  validator_started: '校验内容',
  validator_completed: '校验完成',
  retrying: '重试中',
  summarizer_started: '整合结果',
  summarizer_completed: '整合完成',
  verbatim_started: '查找原文',
  verbatim_completed: '读取原文',
  memory_started: '整理记忆',
}

const MODE_LABELS: Record<string, string> = {
  direct: '直接回答',
  brief: '简洁回答',
  longform: '长文',
  verbatim: '原文输出',
}

export function stageLabel(stage?: string | null): string | null {
  if (!stage) return null
  return STAGE_LABELS[stage] ?? null
}

export function modeLabel(mode?: string | null): string | null {
  if (!mode) return null
  return MODE_LABELS[mode] ?? mode
}

/** 胶囊的悬停说明：优先展示后端给的阶段消息。 */
export function runningTaskStage(task: Pick<TaskSummary, 'stage' | 'message'>): string {
  const message = task.message?.trim()
  if (message) return message
  return stageLabel(task.stage) ?? '执行中'
}

/** 单行标题（过长截断，避免胶囊撑开顶栏）。 */
export function runningTaskTitle(query: string, max = 16): string {
  const text = query.replace(/\s+/g, ' ').trim()
  if (!text) return '未命名任务'
  if (text.length <= max) return text
  return `${text.slice(0, Math.max(1, max - 1))}…`
}

/** 从 created_at 到现在的秒数（解析失败按 0 处理）。 */
export function elapsedSeconds(createdAt?: string | null, now = Date.now()): number {
  if (!createdAt) return 0
  const start = Date.parse(createdAt)
  if (Number.isNaN(start)) return 0
  return Math.max(0, Math.floor((now - start) / 1000))
}

/**
 * 拆分「直接展示」与「折叠进下拉」的胶囊。
 *
 * 正在观察的任务优先占据一个位置（否则用户当前看的任务反而被折叠）；
 * 其余按后端返回顺序（最新在前）补齐。
 */
export function sliceRunningTasks(
  tasks: readonly TaskSummary[],
  options: { limit?: number; activeTaskId?: string | null } = {},
): { visible: TaskSummary[]; overflow: TaskSummary[] } {
  const limit = Math.max(1, options.limit ?? MAX_VISIBLE_CAPSULES)
  if (tasks.length <= limit) return { visible: [...tasks], overflow: [] }

  const active = options.activeTaskId
    ? tasks.find((task) => task.task_id === options.activeTaskId)
    : undefined
  const visible: TaskSummary[] = active ? [active] : tasks.slice(0, limit)
  for (const task of tasks) {
    if (visible.length >= limit) break
    if (!visible.includes(task)) visible.push(task)
  }
  return {
    visible,
    overflow: tasks.filter((task) => !visible.includes(task)),
  }
}

/**
 * 胶囊内容签名：只包含影响顶栏展示的字段。
 *
 * 轮询每 5s 拉一次列表；内容没变时用它跳过 `setState`，避免无意义的
 * 全量重渲染（`useTaskRun` 的消费者会跟着 provider 一起重渲染）。
 */
export function pillsSignature(tasks: readonly TaskSummary[]): string {
  return tasks
    .map((task) =>
      [
        task.task_id,
        task.status,
        task.stage ?? '',
        task.message ?? '',
        task.finished_at ?? '',
        task.error_type ?? '',
      ].join('\u0001'),
    )
    .join('\u0002')
}
