// @vitest-environment happy-dom
import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test'

import type { Plan, Source, TaskEvent, TaskSummary, WritingBudget } from '../types/api'
import { loadAcknowledgedTasks } from '../utils/runningTasks'
import { DEFAULT_PILL_SETTINGS, readPillSettings, writePillSettings } from '../utils/pillSettings'
import { NavProvider, useNav } from './nav'
import type { PageKey } from './nav'
import { TaskRunProvider, useTaskRun } from './taskRun'

const mocks = vi.hoisted(() => ({
  streamTask: vi.fn(),
  streamResume: vi.fn(),
  streamRerun: vi.fn(),
  streamObserve: vi.fn(),
  cancelTask: vi.fn(),
  listTasks: vi.fn(),
  getTask: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    streamTask: mocks.streamTask,
    streamResume: mocks.streamResume,
    streamRerun: mocks.streamRerun,
    streamObserve: mocks.streamObserve,
    cancelTask: mocks.cancelTask,
    listTasks: mocks.listTasks,
    getTask: mocks.getTask,
  }
})

const plan: Plan = {
  goal: '写一篇 RAG 综述',
  needs_retrieval: true,
  steps: [{ id: 'research', type: 'retrieval', description: '检索资料' }],
}

const budget: WritingBudget = {
  requested_chars: 6000,
  source_chars: 8000,
  source_count: 2,
  effective_chars: 6000,
  source_limited: false,
  no_sources: false,
  recommended_sections: 2,
  reason: '资料充足',
}

const source: Source = {
  index: 1,
  document_id: 'doc-1',
  filename: 'rag.pdf',
  page: 3,
  chunk_id: 'doc-1-0',
  score: 0.82,
}

function ev(event: string, extra: Partial<TaskEvent> = {}): TaskEvent {
  return {
    task_id: 'run-1',
    event,
    status: 'running',
    message: event,
    ...extra,
  }
}

let navigateTo: ((page: PageKey) => void) | null = null

/** 让测试可以真正切页（「离开工作台后完成」的胶囊提醒依赖当前页面）。 */
function NavProbe() {
  navigateTo = useNav().navigate
  return null
}

function wrapper({ children }: { children: ReactNode }) {
  return (
    <NavProvider>
      <TaskRunProvider>
        <NavProbe />
        {children}
      </TaskRunProvider>
    </NavProvider>
  )
}

async function runScript(script: TaskEvent[], query = '写一篇 RAG 综述') {
  mocks.streamTask.mockImplementation(
    async (_query: string, onEvent: (event: TaskEvent) => void) => {
      for (const event of script) onEvent(event)
    },
  )
  const { result } = renderHook(() => useTaskRun(), { wrapper })
  act(() => result.current.setQuery(query))
  await act(async () => {
    await result.current.run()
  })
  return result
}

beforeEach(() => {
  localStorage.clear()
  navigateTo = null
  mocks.streamTask.mockReset()
  mocks.streamResume.mockReset()
  mocks.streamRerun.mockReset()
  mocks.streamObserve.mockReset()
  mocks.cancelTask.mockReset()
  mocks.listTasks.mockReset()
  mocks.getTask.mockReset()
  mocks.listTasks.mockResolvedValue({ tasks: [] })
  mocks.cancelTask.mockResolvedValue({ task_id: 'run-1', status: 'cancelled' })
})

afterEach(cleanup)

describe('TaskRunProvider 初始状态', () => {
  it('空运行时的默认值与可写状态', () => {
    const { result } = renderHook(() => useTaskRun(), { wrapper })

    expect(result.current.running).toBe(false)
    expect(result.current.hasStarted).toBe(false)
    expect(result.current.query).toBe('')
    expect(result.current.depth).toBe('auto')
    expect(result.current.useSkills).toBe(false)
    expect(result.current.activeTab).toBe('content')
    expect(result.current.log).toEqual([])
    expect(Object.values(result.current.nodes).every((value) => value === 'wait')).toBe(true)

    act(() => {
      result.current.setQuery('自定义问题')
      result.current.setDepth('longform')
      result.current.setUseSkills(true)
      result.current.setActiveTab('plan')
    })
    expect(result.current.query).toBe('自定义问题')
    expect(result.current.depth).toBe('longform')
    expect(result.current.useSkills).toBe(true)
    expect(result.current.activeTab).toBe('plan')

    act(() => result.current.clear())
    expect(result.current.hasStarted).toBe(false)
    expect(result.current.activeTab).toBe('content')
    // clear 只重置运行态，输入框内容保留给用户继续修改
    expect(result.current.query).toBe('自定义问题')
  })
})

describe('TaskRunProvider 事件归并', () => {
  it('完成一次长文运行后汇总章节、来源与结果', async () => {
    const result = await runScript([
      ev('task_started', { mode: 'longform' }),
      ev('planner_started'),
      ev('planner_completed', { plan }),
      ev('researcher_completed', { sources: [source], retrieved_count: 1 }),
      ev('outline_completed', { outline: ['背景', '方法'], writing_budget: budget }),
      ev('writer_started', { step: 'chapter_1' }),
      ev('writer_completed', { step: 'chapter_1' }),
      ev('validator_completed', { target: 'chapter_1', passed: true }),
      ev('writer_started', { step: 'chapter_2' }),
      ev('writer_completed', { step: 'chapter_2' }),
      ev('validator_completed', { target: 'chapter_2', passed: true }),
      ev('task_completed', {
        result: {
          task_id: 'run-1',
          status: 'completed',
          mode: 'longform',
          plan,
          outline: ['背景', '方法'],
          step_results: [],
          sources: [source],
          validation: {
            passed: true,
            issues: [],
            suggested_action: 'continue',
            target: 'document',
          },
          retry_count: 0,
          failed_chapters: [],
          final_answer: '# RAG 综述',
          usage: null,
        },
      }),
    ])

    expect(result.current.running).toBe(false)
    expect(result.current.hasStarted).toBe(true)
    expect(result.current.taskId).toBe('run-1')
    expect(result.current.mode).toBe('longform')
    expect(result.current.outline).toEqual(['背景', '方法'])
    expect(result.current.chapterList).toHaveLength(2)
    expect(result.current.writtenChapters).toBe(2)
    expect(result.current.passedCount).toBe(2)
    expect(result.current.failedCount).toBe(0)
    expect(result.current.sources).toEqual([source])
    expect(result.current.retrievedCount).toBe(1)
    expect(result.current.finalAnswer).toBe('# RAG 综述')
    expect(result.current.nodes.writer).toBe('finish')
    expect(result.current.nodes.validator).toBe('finish')
    expect(result.current.log.length).toBeGreaterThan(0)
  })

  it('计划声明无需检索时直接收起 researcher', async () => {
    const result = await runScript([
      ev('task_started', { mode: 'brief' }),
      ev('planner_completed', {
        plan: { goal: '回答问题', needs_retrieval: false, steps: [] },
      }),
    ])

    expect(result.current.retrievalSkipped).toBe(true)
    expect(result.current.nodes.researcher).toBe('finish')
  })

  it('章级重试耗尽时标记该章失败并保留提示', async () => {
    const result = await runScript([
      ev('task_started'),
      ev('outline_completed', { outline: ['背景', '方法'] }),
      ev('retrying', {
        target: 'chapter_2',
        suggested_action: 'retry_writer',
        exhausted: true,
        message: '第 2 章重写次数已达上限',
      }),
    ])

    expect(result.current.failedCount).toBe(1)
    expect(result.current.chapterList[1].validation).toBe('failed')
    expect(result.current.chapterNotes[2]).toEqual(['第 2 章重写次数已达上限'])
  })

  it('replan 进入下一轮并清空章节进度', async () => {
    const result = await runScript([
      ev('task_started'),
      ev('outline_completed', { outline: ['背景'] }),
      ev('writer_completed', { step: 'chapter_1' }),
      ev('retrying', {
        target: 'document',
        suggested_action: 'replan',
        message: '计划需要调整',
      }),
    ])

    expect(result.current.round).toBe(2)
    expect(result.current.outline).toEqual(['背景'])
    expect(result.current.writtenChapters).toBe(0)
    expect(result.current.plannerNotes).toEqual(['第 1 轮：计划需要调整'])
    expect(result.current.chapterNotes).toEqual({})
  })

  it('用户终止后记录 aborted 并把运行中节点收回', async () => {
    mocks.streamTask.mockImplementation(
      async (_query: string, onEvent: (event: TaskEvent) => void) => {
        onEvent(ev('task_started'))
        onEvent(ev('planner_started'))
        const abortError = Object.assign(new Error('aborted'), { name: 'AbortError' })
        throw abortError
      },
    )
    const { result } = renderHook(() => useTaskRun(), { wrapper })
    act(() => result.current.setQuery('会中断的任务'))
    await act(async () => {
      await result.current.run()
    })

    expect(result.current.running).toBe(false)
    expect(result.current.aborted).toBe(true)
    expect(result.current.error).toBeNull()
    expect(result.current.nodes.planner).toBe('wait')
    expect(result.current.log.some((entry) => entry.label === '终止')).toBe(true)
  })
})

/** 等待挂载效果 / 异步回调落地（listTasks -> attach -> streamObserve）。 */
async function flush() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

function runningTask(taskId: string, extra: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: taskId,
    query: `任务 ${taskId}`,
    status: 'running',
    created_at: new Date().toISOString(),
    retry_count: 0,
    failed_chapters: [],
    ...extra,
  }
}

describe('TaskRunProvider 刷新恢复与多任务', () => {
  it('挂载时自动接上最近一个运行中任务并回放进度', async () => {
    const createdAt = new Date(Date.now() - 30_000).toISOString()
    mocks.listTasks.mockResolvedValue({
      tasks: [
        runningTask('run-7', {
          query: '刷新前的任务',
          mode: 'longform',
          created_at: createdAt,
          stage: 'writer_started',
          message: '正在撰写第 1 章',
        }),
      ],
    })
    const captured: Array<(event: TaskEvent) => void> = []
    mocks.streamObserve.mockImplementation(
      async (_taskId: string, onEvent: (event: TaskEvent) => void) => {
        captured.push(onEvent)
        // 回放：任务开始 + 已完成的规划
        onEvent(ev('task_started', { task_id: 'run-7', mode: 'longform' }))
        onEvent(ev('planner_completed', { task_id: 'run-7', plan }))
        await new Promise(() => {}) // 保持订阅打开（任务仍在执行）
      },
    )

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()

    expect(mocks.listTasks).toHaveBeenCalledWith(20)
    expect(result.current.hasStarted).toBe(true)
    expect(result.current.taskId).toBe('run-7')
    expect(result.current.query).toBe('刷新前的任务')
    expect(result.current.mode).toBe('longform')
    expect(result.current.plan).toEqual(plan)
    expect(result.current.running).toBe(true)
    expect(result.current.elapsed).toBeGreaterThanOrEqual(29)
    expect(result.current.runningTasks).toHaveLength(1)
    expect(result.current.runningTasks[0].stage).toBe('writer_started')

    // 终态：耗时按服务端 finished_at 计算，而不是「现在」
    act(() =>
      captured[0](
        ev('task_completed', {
          task_id: 'run-7',
          status: 'completed',
          result: {
            task_id: 'run-7',
            status: 'completed',
            plan,
            outline: [],
            step_results: [],
            sources: [],
            validation: null,
            retry_count: 0,
            failed_chapters: [],
            final_answer: '# 已完成',
          },
        }),
      ),
    )
    expect(result.current.finalAnswer).toBe('# 已完成')
    expect(result.current.duration).toBeGreaterThanOrEqual(29)
  })

  it('切换到另一个任务只断开旧订阅，不取消旧任务', async () => {
    let emitA: ((event: TaskEvent) => void) | null = null
    let signalA: AbortSignal | undefined
    mocks.streamTask.mockImplementation(
      async (_query: string, onEvent: (event: TaskEvent) => void, signal?: AbortSignal) => {
        emitA = onEvent
        signalA = signal
        onEvent(ev('task_started', { task_id: 'A' }))
        await new Promise(() => {}) // A 一直在后台跑
      },
    )
    mocks.getTask.mockResolvedValue({
      ...runningTask('B', { query: '另一个任务' }),
      user_id: 'local-user',
      plan: null,
      outline: [],
      step_results: [],
      sources: [],
      validation: null,
      final_answer: '',
    })
    mocks.streamObserve.mockImplementation(
      async (_taskId: string, onEvent: (event: TaskEvent) => void) => {
        onEvent(ev('task_started', { task_id: 'B', mode: 'brief' }))
        await new Promise(() => {})
      },
    )

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    act(() => result.current.setQuery('任务 A'))
    act(() => {
      void result.current.run()
    })
    await flush()
    expect(result.current.taskId).toBe('A')
    expect(result.current.running).toBe(true)

    act(() => {
      void result.current.selectTask('B')
    })
    await flush()

    expect(result.current.taskId).toBe('B')
    expect(result.current.query).toBe('另一个任务')
    expect(mocks.cancelTask).not.toHaveBeenCalled()
    expect(signalA?.aborted).toBe(true)

    // 旧任务的迟到事件不得污染新观察对象
    act(() => emitA!(ev('planner_completed', { task_id: 'A', plan })))
    expect(result.current.plan).toBeNull()
  })

  it('已有任务运行时仍可新建任务：旧任务转入后台而不是被取消', async () => {
    const signals: AbortSignal[] = []
    mocks.streamTask.mockImplementation(
      async (_query: string, onEvent: (event: TaskEvent) => void, signal?: AbortSignal) => {
        signals.push(signal as AbortSignal)
        onEvent(ev('task_started', { task_id: signals.length === 1 ? 'A' : 'B' }))
        await new Promise(() => {})
      },
    )

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    act(() => result.current.setQuery('任务 A'))
    act(() => {
      void result.current.run()
    })
    await flush()

    act(() => {
      void result.current.run('任务 B')
    })
    await flush()

    expect(mocks.streamTask).toHaveBeenCalledTimes(2)
    expect(result.current.taskId).toBe('B')
    expect(signals[0].aborted).toBe(true)
    expect(mocks.cancelTask).not.toHaveBeenCalled()
  })

  it('clear 只断开观察不取消任务，随后可启动并行任务', async () => {
    const signals: AbortSignal[] = []
    mocks.streamTask.mockImplementation(
      async (_query: string, onEvent: (event: TaskEvent) => void, signal?: AbortSignal) => {
        signals.push(signal as AbortSignal)
        onEvent(ev('task_started', { task_id: signals.length === 1 ? 'A' : 'B' }))
        await new Promise(() => {})
      },
    )

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    act(() => result.current.setQuery('任务 A'))
    act(() => {
      void result.current.run()
    })
    await flush()
    expect(result.current.taskId).toBe('A')

    // 「新建任务」：只断开 A 的观察，A 继续在后台运行
    const listCallsBeforeClear = mocks.listTasks.mock.calls.length
    act(() => result.current.clear())
    expect(result.current.hasStarted).toBe(false)
    expect(result.current.running).toBe(false)
    expect(signals[0].aborted).toBe(true)
    expect(mocks.cancelTask).not.toHaveBeenCalled()
    // 立即刷新一次任务列表，旧任务能马上出现在胶囊里
    expect(mocks.listTasks.mock.calls.length).toBeGreaterThan(listCallsBeforeClear)

    act(() => {
      void result.current.run('任务 B')
    })
    await flush()

    expect(mocks.streamTask).toHaveBeenCalledTimes(2)
    expect(result.current.taskId).toBe('B')
    expect(result.current.running).toBe(true)
    expect(signals[1].aborted).toBe(false)
  })

  it('终止任意任务调用取消接口并刷新运行中列表', async () => {
    mocks.listTasks.mockResolvedValue({ tasks: [runningTask('X'), runningTask('Y')] })
    mocks.streamObserve.mockResolvedValue(undefined)

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    const before = mocks.listTasks.mock.calls.length

    await act(async () => {
      await result.current.cancelRunning('Y')
    })

    expect(mocks.cancelTask).toHaveBeenCalledWith('Y')
    expect(mocks.listTasks.mock.calls.length).toBeGreaterThan(before)
  })

  it('task_cancelled 终态按已终止收尾', async () => {
    const result = await runScript([
      ev('task_started'),
      ev('task_cancelled', { status: 'cancelled', message: '任务已被终止' }),
    ])

    expect(result.current.aborted).toBe(true)
    expect(result.current.running).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.log.some((entry) => entry.label === '终止')).toBe(true)
  })
})

function endedTask(
  taskId: string,
  extra: Partial<TaskSummary> = {},
  status: 'completed' | 'failed' | 'cancelled' = 'completed',
): TaskSummary {
  return runningTask(taskId, {
    status,
    finished_at: new Date().toISOString(),
    ...extra,
  })
}

function resultPayload(taskId: string) {
  return {
    task_id: taskId,
    status: 'completed',
    plan: null,
    outline: [],
    step_results: [],
    sources: [],
    validation: null,
    retry_count: 0,
    failed_chapters: [],
    final_answer: '# 完成',
  }
}

describe('顶栏胶囊设置（设置页维护）', () => {
  it('默认值来自 pillSettings，调小上限立即裁剪并持久化', async () => {
    mocks.listTasks.mockResolvedValueOnce({ tasks: [] })
    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    expect(result.current.pillSettings).toEqual(DEFAULT_PILL_SETTINGS)

    const finished = [
      endedTask('fail-1', {}, 'failed'),
      ...Array.from({ length: 4 }, (_, index) =>
        endedTask(
          `ok-${index}`,
          { finished_at: new Date(Date.now() - 1000 * (index + 1)).toISOString() },
          'completed',
        ),
      ),
    ]
    mocks.listTasks.mockResolvedValue({ tasks: finished })
    // 启动恢复受 restoreLimit 限制；这里借一次列表刷新模拟会话内新增的待查看提醒
    await act(async () => {
      await result.current.cancelRunning('other')
    })
    expect(result.current.finishedTasks).toHaveLength(5)

    act(() => result.current.updatePillSettings({ pendingLimit: 2 }))

    // 失败任务豁免，非失败只留最新 2 条
    expect(result.current.finishedTasks.map((task) => task.task_id)).toEqual([
      'fail-1',
      'ok-0',
      'ok-1',
    ])
    expect(readPillSettings().pendingLimit).toBe(2)
    const acknowledged = loadAcknowledgedTasks()
    expect(acknowledged.has('ok-2')).toBe(true)
    expect(acknowledged.has('fail-1')).toBe(false)

    // 调大上限不会把已归档的提醒找回来
    act(() => result.current.updatePillSettings({ pendingLimit: 5 }))
    expect(result.current.finishedTasks).toHaveLength(3)
  })

  it('刷新恢复遵循自定义窗口与条数', async () => {
    writePillSettings({ pendingLimit: 5, restoreWindowHours: 1, restoreLimit: 1 })
    const now = Date.now()
    mocks.listTasks.mockResolvedValue({
      tasks: [
        endedTask('recent', { finished_at: new Date(now - 5 * 60 * 1000).toISOString() }),
        endedTask('half-hour', { finished_at: new Date(now - 30 * 60 * 1000).toISOString() }),
        endedTask('too-old', { finished_at: new Date(now - 2 * 60 * 60 * 1000).toISOString() }),
      ],
    })

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()

    // 2 小时前的任务在 1 小时窗口外；窗口内最多恢复 1 条（最新）
    expect(result.current.finishedTasks.map((task) => task.task_id)).toEqual(['recent'])
  })

  it('清除「已查看」记录后，最近结束的任务重新出现在待查看里', async () => {
    mocks.listTasks.mockResolvedValue({ tasks: [endedTask('done-9')] })

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    expect(result.current.finishedTasks).toHaveLength(1)

    act(() => result.current.ackFinished('done-9'))
    expect(result.current.finishedTasks).toHaveLength(0)
    expect(loadAcknowledgedTasks().has('done-9')).toBe(true)

    act(() => result.current.clearAcknowledged())
    await flush()

    expect(loadAcknowledgedTasks().size).toBe(0)
    expect(result.current.finishedTasks.map((task) => task.task_id)).toEqual(['done-9'])
  })
})

describe('完成态胶囊（常驻待查看）', () => {
  it('启动时恢复最近完成且未查看的任务，关闭后持久化不再出现', async () => {
    mocks.listTasks.mockResolvedValue({ tasks: [endedTask('done-1')] })

    const first = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    expect(first.result.current.finishedTasks.map((task) => task.task_id)).toEqual(['done-1'])

    act(() => first.result.current.ackFinished('done-1'))
    expect(first.result.current.finishedTasks).toHaveLength(0)
    expect(loadAcknowledgedTasks().has('done-1')).toBe(true)

    first.unmount()
    const second = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    expect(second.result.current.finishedTasks).toHaveLength(0)
  })

  it('超过恢复窗口的旧任务不会重新弹出', async () => {
    mocks.listTasks.mockResolvedValue({
      tasks: [
        endedTask('old', {
          finished_at: new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString(),
        }),
      ],
    })

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    expect(result.current.finishedTasks).toHaveLength(0)
  })

  it('正在工作台观察的任务完成时不弹胶囊，并记为已查看', async () => {
    mocks.listTasks
      .mockResolvedValueOnce({ tasks: [] })
      .mockResolvedValue({ tasks: [endedTask('run-1')] })
    mocks.streamTask.mockImplementation(
      async (_query: string, onEvent: (event: TaskEvent) => void) => {
        onEvent(ev('task_started', { task_id: 'run-1' }))
        onEvent(
          ev('task_completed', {
            task_id: 'run-1',
            status: 'completed',
            result: resultPayload('run-1'),
          }),
        )
      },
    )

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    act(() => result.current.setQuery('写一篇综述'))
    await act(async () => {
      await result.current.run()
    })

    expect(result.current.finishedTasks).toHaveLength(0)
    expect(loadAcknowledgedTasks().has('run-1')).toBe(true)
  })

  it('离开工作台后完成的任务进入胶囊，查看或关闭后消失', async () => {
    mocks.listTasks.mockResolvedValue({ tasks: [runningTask('X')] })
    mocks.streamObserve.mockImplementation(
      async (_taskId: string, onEvent: (event: TaskEvent) => void) => {
        onEvent(ev('task_started', { task_id: 'X' }))
        await new Promise(() => {})
      },
    )

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    expect(result.current.runningTasks).toHaveLength(1)

    act(() => navigateTo?.('history'))
    mocks.listTasks.mockResolvedValue({ tasks: [endedTask('X')] })
    // 任意一次列表刷新即可发现后台任务已结束（这里借用取消接口触发的刷新）
    await act(async () => {
      await result.current.cancelRunning('other')
    })

    expect(result.current.finishedTasks.map((task) => task.task_id)).toEqual(['X'])

    // 点击胶囊 / 关闭提醒都会调用 ackFinished
    act(() => result.current.ackFinished('X'))
    expect(result.current.finishedTasks).toHaveLength(0)
    expect(loadAcknowledgedTasks().has('X')).toBe(true)
  })

  it('通过 selectTask 打开已完成任务时自动移除胶囊', async () => {
    mocks.listTasks.mockResolvedValue({ tasks: [endedTask('done-2')] })
    mocks.streamObserve.mockImplementation(
      async (taskId: string, onEvent: (event: TaskEvent) => void) => {
        onEvent(
          ev('task_completed', {
            task_id: taskId,
            status: 'completed',
            result: resultPayload(taskId),
          }),
        )
      },
    )

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    expect(result.current.finishedTasks).toHaveLength(1)

    await act(async () => {
      await result.current.selectTask('done-2')
    })

    expect(result.current.finishedTasks).toHaveLength(0)
    expect(result.current.finalAnswer).toBe('# 完成')
    expect(loadAcknowledgedTasks().has('done-2')).toBe(true)
  })

  it('续跑复用 task_id 时清除「已查看」标记，新的终态仍会提醒', async () => {
    mocks.listTasks
      .mockResolvedValueOnce({ tasks: [endedTask('done-3')] })
      .mockResolvedValue({ tasks: [runningTask('done-3')] })
    mocks.streamResume.mockResolvedValue(undefined)

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    act(() => result.current.ackFinished('done-3'))
    expect(loadAcknowledgedTasks().has('done-3')).toBe(true)

    await act(async () => {
      await result.current.resume('done-3')
    })

    expect(loadAcknowledgedTasks().has('done-3')).toBe(false)
    expect(result.current.finishedTasks).toHaveLength(0)
  })

  it('会话内待查看超过 5 条时自动标为已查看，失败任务不被丢弃', async () => {
    mocks.listTasks.mockResolvedValueOnce({ tasks: [] })
    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()

    const finished = [
      endedTask('fail-1', { finished_at: new Date(Date.now() - 100).toISOString() }, 'failed'),
      ...Array.from({ length: 7 }, (_, index) =>
        endedTask(
          `ok-${index}`,
          { finished_at: new Date(Date.now() - 1000 * (index + 1)).toISOString() },
          'completed',
        ),
      ),
    ]
    mocks.listTasks.mockResolvedValue({ tasks: finished })
    // 任意一次列表刷新即可触发（这里借用取消接口，它内部会 refreshTasks）
    await act(async () => {
      await result.current.cancelRunning('other')
    })

    const kept = result.current.finishedTasks.map((task) => task.task_id)
    // 失败任务豁免：1 个失败 + 最新 5 条已完成
    expect(kept).toHaveLength(6)
    expect(kept).toContain('fail-1')
    expect(kept).toEqual(['fail-1', 'ok-0', 'ok-1', 'ok-2', 'ok-3', 'ok-4'])
    // 被丢弃的条目写入「已查看」，不会再反复弹出
    const acknowledged = loadAcknowledgedTasks()
    expect(acknowledged.has('ok-5')).toBe(true)
    expect(acknowledged.has('ok-6')).toBe(true)
    expect(acknowledged.has('fail-1')).toBe(false)
  })

  it('批量标为已查看：清空所有待查看并持久化', async () => {
    mocks.listTasks.mockResolvedValue({
      tasks: [endedTask('done-a'), endedTask('done-b', {}, 'failed')],
    })

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()
    expect(result.current.finishedTasks).toHaveLength(2)

    act(() => result.current.ackAllFinished())
    expect(result.current.finishedTasks).toHaveLength(0)

    const acknowledged = loadAcknowledgedTasks()
    expect(acknowledged.has('done-a')).toBe(true)
    expect(acknowledged.has('done-b')).toBe(true)
  })

  it('失败与已终止的任务同样常驻，状态来自后端记录', async () => {
    mocks.listTasks.mockResolvedValue({
      tasks: [
        endedTask(
          'f-1',
          {
            error_type: 'llm_timeout',
            finished_at: new Date(Date.now() - 2000).toISOString(),
          },
          'failed',
        ),
        endedTask('c-1', { finished_at: new Date(Date.now() - 1000).toISOString() }, 'cancelled'),
      ],
    })

    const { result } = renderHook(() => useTaskRun(), { wrapper })
    await flush()

    expect(
      Object.fromEntries(result.current.finishedTasks.map((task) => [task.task_id, task.status])),
    ).toEqual({ 'f-1': 'failed', 'c-1': 'cancelled' })
  })
})
