// @vitest-environment happy-dom
import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test'

import type { Plan, Source, TaskEvent, TaskSummary, WritingBudget } from '../types/api'
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

function wrapper({ children }: { children: ReactNode }) {
  return <TaskRunProvider>{children}</TaskRunProvider>
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

    expect(mocks.listTasks).toHaveBeenCalledWith(20, 'running')
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
