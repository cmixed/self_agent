/** 预设任务在工作台 / 预设页共用的纯逻辑。 */

import type { PresetInfo, TaskSummary } from '../types/api'

/** 工作台直接展示的预设数量；其余进入「更多」下拉。 */
export const WORKSPACE_PRESET_LIMIT = 6

/**
 * 选出「上次任务」卡片使用的任务：最近一次**已结束**的任务。
 *
 * 运行中的任务不能直接 rerun（后端会 409），所以跳过；找不到时返回 null。
 */
export function pickLastTask(tasks: readonly TaskSummary[]): TaskSummary | null {
  return tasks.find((task) => task.status !== 'running') ?? null
}

/** 把工作台预设拆成「直接显示」与「更多下拉」两组（保持后端顺序）。 */
export function splitWorkspacePresets(
  presets: readonly PresetInfo[],
  limit: number = WORKSPACE_PRESET_LIMIT,
): { visible: PresetInfo[]; hidden: PresetInfo[] } {
  const size = Math.max(0, Math.floor(limit))
  return {
    visible: presets.slice(0, size),
    hidden: presets.slice(size),
  }
}

/**
 * 把 `activeId` 移动到 `overId` 的位置（拖拽排序用）。
 *
 * 找不到任一项或位置相同时返回原数组（调用方据此跳过请求）。
 */
export function movePreset(
  presets: readonly PresetInfo[],
  activeId: string,
  overId: string,
): PresetInfo[] {
  const from = presets.findIndex((preset) => preset.preset_id === activeId)
  const to = presets.findIndex((preset) => preset.preset_id === overId)
  if (from < 0 || to < 0 || from === to) return presets as PresetInfo[]

  const next = [...presets]
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return next.map((preset, index) => ({ ...preset, sort_order: index }))
}
