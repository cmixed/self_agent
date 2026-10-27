import { describe, expect, it, vi } from 'vite-plus/test'

import type { TaskSummary } from '../types/api'
import {
  elapsedSeconds,
  MAX_VISIBLE_CAPSULES,
  modeLabel,
  runningTaskStage,
  runningTaskTitle,
  sliceRunningTasks,
  stageLabel,
} from './runningTasks'

function task(taskId: string, extra: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: taskId,
    query: `任务 ${taskId}`,
    status: 'running',
    created_at: '2026-01-01T00:00:00Z',
    retry_count: 0,
    failed_chapters: [],
    ...extra,
  }
}

describe('runningTaskStage', () => {
  it('优先展示后端给的阶段消息', () => {
    expect(runningTaskStage({ stage: 'writer_started', message: '正在撰写第 2 章' })).toBe(
      '正在撰写第 2 章',
    )
  })

  it('没有消息时回退到事件名文案', () => {
    expect(runningTaskStage({ stage: 'writer_started', message: null })).toBe('撰写章节')
    expect(stageLabel('retrying')).toBe('重试中')
    expect(runningTaskStage({ stage: 'unknown_event' })).toBe('执行中')
    expect(runningTaskStage({})).toBe('执行中')
  })
})

describe('runningTaskTitle', () => {
  it('压缩空白并截断过长标题', () => {
    expect(runningTaskTitle('  写一篇\n RAG 综述 ')).toBe('写一篇 RAG 综述')
    expect(runningTaskTitle('一'.repeat(30), 10)).toBe(`${'一'.repeat(9)}…`)
    expect(runningTaskTitle('   ')).toBe('未命名任务')
  })
})

describe('elapsedSeconds', () => {
  it('按创建时间计算并容错', () => {
    const now = Date.parse('2026-01-01T00:01:30Z')
    expect(elapsedSeconds('2026-01-01T00:00:00Z', now)).toBe(90)
    expect(elapsedSeconds(null, now)).toBe(0)
    expect(elapsedSeconds('not-a-date', now)).toBe(0)
  })
})

describe('modeLabel', () => {
  it('映射执行模式', () => {
    expect(modeLabel('longform')).toBe('长文')
    expect(modeLabel('brief')).toBe('简洁回答')
    expect(modeLabel(null)).toBeNull()
    expect(modeLabel('custom')).toBe('custom')
  })
})

describe('sliceRunningTasks', () => {
  it('不超过上限时全部展示', () => {
    const tasks = [task('a'), task('b')]
    expect(sliceRunningTasks(tasks)).toEqual({ visible: tasks, overflow: [] })
    expect(MAX_VISIBLE_CAPSULES).toBe(2)
  })

  it('没有活动任务时保留最新的若干个', () => {
    const tasks = [task('a'), task('b'), task('c'), task('d')]
    const { visible, overflow } = sliceRunningTasks(tasks, { limit: 2 })
    expect(visible.map((item) => item.task_id)).toEqual(['a', 'b'])
    expect(overflow.map((item) => item.task_id)).toEqual(['c', 'd'])
  })

  it('活动任务优先展示，其余按原顺序补齐', () => {
    const tasks = [task('a'), task('b'), task('c'), task('d')]
    const { visible, overflow } = sliceRunningTasks(tasks, { limit: 2, activeTaskId: 'c' })
    expect(visible.map((item) => item.task_id)).toEqual(['c', 'a'])
    expect(overflow.map((item) => item.task_id)).toEqual(['b', 'd'])
  })

  it('活动任务不在列表里时按默认顺序展示', () => {
    const tasks = [task('a'), task('b'), task('c')]
    const { visible } = sliceRunningTasks(tasks, { limit: 2, activeTaskId: 'zzz' })
    expect(visible.map((item) => item.task_id)).toEqual(['a', 'b'])
  })

  it('不修改入参', () => {
    const tasks = [task('a'), task('b'), task('c')]
    const copy = [...tasks]
    sliceRunningTasks(tasks, { limit: 1, activeTaskId: 'b' })
    expect(tasks).toEqual(copy)
  })
})

describe('时间显示', () => {
  it('elapsedSeconds 不依赖真实时钟', () => {
    const spy = vi.spyOn(Date, 'now')
    spy.mockReturnValue(Date.parse('2026-01-01T00:00:10Z'))
    expect(elapsedSeconds('2026-01-01T00:00:00Z')).toBe(10)
    spy.mockRestore()
  })
})
