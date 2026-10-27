import { describe, expect, it, vi } from 'vite-plus/test'

import type { TaskSummary } from '../types/api'
import {
  ACKNOWLEDGED_STORAGE_KEY,
  collectFinishedTasks,
  DEFAULT_VISIBLE_CAPSULES,
  elapsedSeconds,
  groupTaskPills,
  isTerminalStatus,
  loadAcknowledgedTasks,
  MAX_PENDING_FINISHED,
  MAX_VISIBLE_CAPSULES,
  mergeTaskPills,
  modeLabel,
  overflowSummary,
  pillCounts,
  pillStatusLabel,
  runningTaskStage,
  runningTaskTitle,
  saveAcknowledgedTasks,
  sliceRunningTasks,
  splitPendingFinished,
  stageLabel,
  taskPillState,
  visibleCapsuleCount,
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
    expect(MAX_VISIBLE_CAPSULES).toBe(4)
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
  it('失败待查看优先，其次运行中，最后已完成；且不重复', () => {
    const running = [task('r1'), task('r2')]
    const finished = [
      task('d-old', { status: 'completed', finished_at: '2026-01-01T00:00:00Z' }),
      task('r1', { status: 'completed', finished_at: '2026-01-01T02:00:00Z' }),
      task('d-new', { status: 'failed', finished_at: '2026-01-01T03:00:00Z' }),
    ]

    expect(mergeTaskPills(running, finished).map((item) => item.task_id)).toEqual([
      'd-new',
      'r1',
      'r2',
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

describe('visibleCapsuleCount', () => {
  it('宽度未知时回退默认数量', () => {
    expect(DEFAULT_VISIBLE_CAPSULES).toBe(2)
    expect(visibleCapsuleCount(6, 0)).toBe(2)
    expect(visibleCapsuleCount(1, 0)).toBe(1)
    expect(visibleCapsuleCount(0, 800)).toBe(0)
  })

  it('全部放得下时展示全部', () => {
    expect(visibleCapsuleCount(2, 800)).toBe(2)
  })

  it('放不下时预留 +N 的位置', () => {
    // 190*2 + 8 + 8 + 60 = 456 <= 600，第三个需要 654 > 600
    expect(visibleCapsuleCount(6, 600)).toBe(2)
  })

  it('宽屏最多展示 4 个', () => {
    expect(visibleCapsuleCount(10, 5000)).toBe(MAX_VISIBLE_CAPSULES)
  })

  it('极窄宽度也至少展示 1 个（靠 CSS 收缩兜底）', () => {
    expect(visibleCapsuleCount(6, 100)).toBe(1)
  })

  it('支持自定义尺寸', () => {
    expect(visibleCapsuleCount(6, 300, { pillWidth: 100, moreWidth: 40, gap: 4, max: 3 })).toBe(2)
  })
})

describe('splitPendingFinished', () => {
  const ended = (id: string, status = 'completed', secondsAgo = 0) =>
    task(id, {
      status,
      finished_at: new Date(Date.now() - secondsAgo * 1000).toISOString(),
    })

  it('非失败任务只保留最新 limit 条', () => {
    const tasks = Array.from({ length: 8 }, (_, index) => ended(`t-${index}`, 'completed', index))
    const { kept, dropped } = splitPendingFinished(tasks, 5)
    expect(kept.map((item) => item.task_id)).toEqual(['t-0', 't-1', 't-2', 't-3', 't-4'])
    expect(dropped.map((item) => item.task_id)).toEqual(['t-5', 't-6', 't-7'])
  })

  it('失败任务永不自动丢弃（可超过上限）', () => {
    const tasks = [
      ended('failed-1', 'failed', 0),
      ended('failed-2', 'failed', 1),
      ...Array.from({ length: 8 }, (_, index) => ended(`t-${index}`, 'completed', index + 2)),
    ]
    const { kept, dropped } = splitPendingFinished(tasks, MAX_PENDING_FINISHED)
    expect(kept.filter((item) => item.status === 'failed')).toHaveLength(2)
    expect(kept).toHaveLength(2 + MAX_PENDING_FINISHED)
    expect(dropped).toHaveLength(3)
  })
})

describe('groupTaskPills / pillCounts', () => {
  it('按待查看（失败置顶）→ 执行中分组', () => {
    const groups = groupTaskPills([
      task('run-1'),
      task('done-1', { status: 'completed', finished_at: '2026-01-01T00:00:00Z' }),
      task('fail-1', { status: 'failed', finished_at: '2026-01-01T01:00:00Z' }),
    ])

    expect(groups.map((group) => group.label)).toEqual(['待查看（2）', '执行中（1）'])
    expect(groups[0].tasks.map((item) => item.task_id)).toEqual(['fail-1', 'done-1'])
    expect(groups[1].tasks.map((item) => item.task_id)).toEqual(['run-1'])
  })

  it('只有一种状态时只有一个分组', () => {
    expect(groupTaskPills([task('run-1')])).toHaveLength(1)
    expect(groupTaskPills([])).toEqual([])
  })

  it('统计构成并生成 +N 说明', () => {
    const tasks = [
      task('run-1'),
      task('done-1', { status: 'completed' }),
      task('fail-1', { status: 'failed' }),
    ]
    expect(pillCounts(tasks)).toEqual({ running: 1, pending: 2, failed: 1 })
    expect(overflowSummary(tasks)).toBe(
      '另有 3 个任务未显示：1 个执行中、2 个待查看（含 1 个失败）',
    )
  })
})
