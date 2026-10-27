import { describe, expect, it, vi } from 'vite-plus/test'

import type { TaskSummary } from '../types/api'
import {
  ACKNOWLEDGED_STORAGE_KEY,
  collectFinishedTasks,
  elapsedSeconds,
  isTerminalStatus,
  loadAcknowledgedTasks,
  MAX_VISIBLE_CAPSULES,
  mergeTaskPills,
  modeLabel,
  pillStatusLabel,
  runningTaskStage,
  runningTaskTitle,
  saveAcknowledgedTasks,
  sliceRunningTasks,
  stageLabel,
  taskPillState,
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

describe('任务胶囊状态', () => {
  it('区分运行中与三种终态', () => {
    expect(taskPillState({ status: 'running' })).toBe('running')
    expect(taskPillState({ status: 'completed' })).toBe('completed')
    expect(taskPillState({ status: 'failed' })).toBe('failed')
    expect(taskPillState({ status: 'cancelled' })).toBe('cancelled')

    expect(isTerminalStatus('completed')).toBe(true)
    expect(isTerminalStatus('running')).toBe(false)
    expect(isTerminalStatus(null)).toBe(false)

    expect(pillStatusLabel('completed')).toBe('已完成')
    expect(pillStatusLabel('failed')).toBe('失败')
    expect(pillStatusLabel('cancelled')).toBe('已终止')
    expect(pillStatusLabel('running')).toBe('执行中')
  })
})

describe('mergeTaskPills', () => {
  it('运行中在前，完成态按结束时间倒序，且不重复', () => {
    const running = [task('r1'), task('r2')]
    const finished = [
      task('d-old', { status: 'completed', finished_at: '2026-01-01T00:00:00Z' }),
      task('r1', { status: 'completed', finished_at: '2026-01-01T02:00:00Z' }),
      task('d-new', { status: 'failed', finished_at: '2026-01-01T03:00:00Z' }),
    ]

    expect(mergeTaskPills(running, finished).map((item) => item.task_id)).toEqual([
      'r1',
      'r2',
      'd-new',
      'd-old',
    ])
  })
})

describe('collectFinishedTasks', () => {
  const now = Date.parse('2026-01-02T00:00:00Z')
  const recent = (id: string, status = 'completed', minutesAgo = 5) =>
    task(id, {
      status,
      finished_at: new Date(now - minutesAgo * 60_000).toISOString(),
    })

  it('保留已有条目并补上新完成的终态任务', () => {
    const result = collectFinishedTasks({
      tasks: [recent('new-1'), task('still-running')],
      current: [recent('old-1', 'completed', 10)],
      acknowledged: new Set(),
      now,
    })
    expect(result.map((item) => item.task_id).sort()).toEqual(['new-1', 'old-1'])
  })

  it('跳过已查看、正在观察、超窗口与缺少结束时间的任务', () => {
    const result = collectFinishedTasks({
      tasks: [
        recent('acked'),
        recent('watching'),
        recent('too-old', 'completed', 25 * 60),
        task('no-finish', { status: 'completed' }),
      ],
      current: [],
      acknowledged: new Set(['acked']),
      skipIds: new Set(['watching']),
      now,
    })
    expect(result).toEqual([])
  })

  it('同一任务续跑后撤掉旧的完成态（task_id 复用）', () => {
    const result = collectFinishedTasks({
      tasks: [task('resumed', { status: 'running' })],
      current: [recent('resumed')],
      acknowledged: new Set(),
      now,
    })
    expect(result).toEqual([])
  })

  it('可从已有列表补回当前观察任务（切页后仍需提醒）', () => {
    const result = collectFinishedTasks({
      tasks: [],
      current: [recent('watching')],
      acknowledged: new Set(),
      now,
    })
    expect(result.map((item) => item.task_id)).toEqual(['watching'])
  })

  it('limit 只截断恢复时的数量，保留最新的若干条', () => {
    const tasks = [
      recent('a', 'completed', 30),
      recent('b', 'completed', 20),
      recent('c', 'completed', 10),
    ]
    const result = collectFinishedTasks({
      tasks,
      current: [],
      acknowledged: new Set(),
      now,
      limit: 2,
    })
    expect(result.map((item) => item.task_id)).toEqual(['c', 'b'])
  })

  it('按结束时间倒序排列', () => {
    const result = collectFinishedTasks({
      tasks: [recent('a', 'completed', 30), recent('b', 'completed', 10)],
      current: [],
      acknowledged: new Set(),
      now,
    })
    expect(result.map((item) => item.task_id)).toEqual(['b', 'a'])
  })
})

describe('已查看任务的持久化', () => {
  function fakeStorage() {
    const data = new Map<string, string>()
    return {
      data,
      getItem: (key: string) => data.get(key) ?? null,
      setItem: (key: string, value: string) => void data.set(key, value),
      removeItem: (key: string) => void data.delete(key),
    }
  }

  it('保存后可读回，并只保留最近 100 条', () => {
    const storage = fakeStorage()
    const ids = new Set(Array.from({ length: 120 }, (_, index) => `t-${index}`))
    saveAcknowledgedTasks(ids, storage)

    const loaded = loadAcknowledgedTasks(storage)
    expect(loaded.size).toBe(100)
    expect(loaded.has('t-119')).toBe(true)
    expect(loaded.has('t-0')).toBe(false)
  })

  it('数据损坏或不可用时按空集合处理', () => {
    const storage = fakeStorage()
    storage.setItem(ACKNOWLEDGED_STORAGE_KEY, 'not-json')
    expect(loadAcknowledgedTasks(storage).size).toBe(0)
    expect(loadAcknowledgedTasks(null).size).toBe(0)

    storage.setItem(ACKNOWLEDGED_STORAGE_KEY, JSON.stringify([1, '', 'ok']))
    expect([...loadAcknowledgedTasks(storage)]).toEqual(['ok'])
  })
})
