// @vitest-environment happy-dom
import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test'

import type { Plan, Source, TaskEvent, WritingBudget } from '../types/api'
import { TaskRunProvider, useTaskRun } from './taskRun'

const mocks = vi.hoisted(() => ({
  streamTask: vi.fn(),
  streamResume: vi.fn(),
  streamRerun: vi.fn(),
  cancelTask: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    streamTask: mocks.streamTask,
    streamResume: mocks.streamResume,
    streamRerun: mocks.streamRerun,
    cancelTask: mocks.cancelTask,
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
  mocks.cancelTask.mockReset()
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
