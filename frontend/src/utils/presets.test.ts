import { describe, expect, it } from 'vite-plus/test'

import type { PresetInfo, TaskSummary } from '../types/api'
import { movePreset, pickLastTask, splitWorkspacePresets, WORKSPACE_PRESET_LIMIT } from './presets'

function preset(id: string): PresetInfo {
  return {
    preset_id: id,
    title: id,
    description: '',
    query: id,
    scope: null,
    auto_run: false,
    sort_order: 0,
    created_at: '2026-01-01T00:00:00+00:00',
    updated_at: '2026-01-01T00:00:00+00:00',
  }
}

describe('splitWorkspacePresets', () => {
  it('超过上限时拆成直接显示与更多两组', () => {
    const presets = Array.from({ length: 8 }, (_, index) => preset(`p${index}`))
    const { visible, hidden } = splitWorkspacePresets(presets)

    expect(visible.map((item) => item.preset_id)).toEqual(['p0', 'p1', 'p2', 'p3', 'p4', 'p5'])
    expect(hidden.map((item) => item.preset_id)).toEqual(['p6', 'p7'])
    expect(WORKSPACE_PRESET_LIMIT).toBe(6)
  })

  it('不足上限时全部直接显示', () => {
    const presets = [preset('a'), preset('b')]
    const { visible, hidden } = splitWorkspacePresets(presets)
    expect(visible).toHaveLength(2)
    expect(hidden).toHaveLength(0)
  })

  it('非法上限按 0 处理', () => {
    const { visible, hidden } = splitWorkspacePresets([preset('a')], -3)
    expect(visible).toHaveLength(0)
    expect(hidden.map((item) => item.preset_id)).toEqual(['a'])
  })
})

describe('movePreset', () => {
  it('按拖拽方向重排并刷新 sort_order', () => {
    const presets = ['a', 'b', 'c'].map(preset)
    const next = movePreset(presets, 'c', 'a')

    expect(next.map((item) => item.preset_id)).toEqual(['c', 'a', 'b'])
    expect(next.map((item) => item.sort_order)).toEqual([0, 1, 2])
  })

  it('位置相同或找不到目标时返回原数组', () => {
    const presets = ['a', 'b'].map(preset)
    expect(movePreset(presets, 'a', 'a')).toBe(presets)
    expect(movePreset(presets, 'a', 'missing')).toBe(presets)
    expect(movePreset(presets, 'missing', 'a')).toBe(presets)
  })
})

describe('pickLastTask', () => {
  function task(id: string, status: string): TaskSummary {
    return {
      task_id: id,
      query: id,
      status,
      created_at: '2026-01-01T00:00:00+00:00',
      retry_count: 0,
      failed_chapters: [],
    }
  }

  it('跳过运行中的任务，返回最近一次已结束任务', () => {
    expect(pickLastTask([task('run', 'running'), task('done', 'completed')])?.task_id).toBe('done')
  })

  it('没有已结束任务时返回 null', () => {
    expect(pickLastTask([])).toBeNull()
    expect(pickLastTask([task('run', 'running')])).toBeNull()
  })
})
