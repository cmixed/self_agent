/** 顶栏「运行中任务」胶囊的纯逻辑（便于单测，不依赖 React）。 */

import type { TaskSummary } from '../types/api'

/** 桌面端直接展示的胶囊数量上限，超出部分折叠进「+N」下拉。 */
export const MAX_VISIBLE_CAPSULES = 2

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
