/** 顶栏任务胶囊（运行中 / 完成待查看）的纯逻辑（便于单测，不依赖 React）。 */

import type { TaskSummary } from '../types/api'

/** 桌面端直接展示的胶囊数量上限，超出部分折叠进「+N」下拉。 */
export const MAX_VISIBLE_CAPSULES = 2

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

/**
 * 合并「运行中 + 完成待查看」为一条胶囊列表。
 *
 * 运行中排在前（用户正在等待的任务优先），完成态按结束时间倒序；
 * 同一 task_id 只保留一条（切换瞬间可能两边都出现）。
 */
export function mergeTaskPills(
  running: readonly TaskSummary[],
  finished: readonly TaskSummary[],
): TaskSummary[] {
  const seen = new Set<string>()
  const result: TaskSummary[] = []
  for (const task of running) {
    if (seen.has(task.task_id)) continue
    seen.add(task.task_id)
    result.push(task)
  }
  const terminal = finished
    .filter((task) => {
      if (seen.has(task.task_id)) return false
      seen.add(task.task_id)
      return true
    })
    .sort((a, b) => finishTime(b) - finishTime(a))
  return [...result, ...terminal]
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
}

const MODE_LABELS: Record<string, string> = {
  direct: '直接回答',
  brief: '简洁回答',
  longform: '长文',
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
