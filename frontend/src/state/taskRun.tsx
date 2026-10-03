import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import type {
  ChapterValidation,
  ChapterView,
  LogEntry,
  StageStatus,
} from '../components/AgentProgress'
import { ApiError, cancelTask, streamTask } from '../services/api'
import type { Plan, Source, TaskEvent, Validation } from '../types/api'
import { downloadMarkdown } from '../utils/download'

/** 图中真实存在的 6 个节点（用于状态跟踪） */
const NODE_KEYS = ['planner', 'researcher', 'outline', 'writer', 'validator', 'summarizer'] as const
type NodeKey = (typeof NODE_KEYS)[number]

const INITIAL_NODES: Record<NodeKey, StageStatus> = {
  planner: 'wait',
  researcher: 'wait',
  outline: 'wait',
  writer: 'wait',
  validator: 'wait',
  summarizer: 'wait',
}

const NODE_LABELS: Record<string, string> = {
  planner: '规划',
  researcher: '检索',
  outline: '大纲',
  writer: '撰写',
  validator: '校验',
  summarizer: '整合',
  retrying: '重试',
  task_started: '开始',
  task_completed: '完成',
  task_failed: '失败',
}

const MAX_LOG_ENTRIES = 60
// 提示条数兜底：后端预算（每章 ≤2 次重写 × ≤8 章 + ≤2 次 replan）已限制总量，
// 这里再加一层 UI 上限，避免任何异常情况下无限增长。
const MAX_PLANNER_NOTES = 4
const MAX_CHAPTER_NOTES_PER_CHAPTER = 3

interface ChapterState {
  written: number
  writing: boolean
  validation: ChapterValidation
}

const chapterNumber = (value: string | null | undefined): number | null => {
  const match = /^chapter_(\d+)$/.exec(value ?? '')
  return match ? Number(match[1]) : null
}

function markRunningAsError(nodes: Record<NodeKey, StageStatus>): Record<NodeKey, StageStatus> {
  const next = { ...nodes }
  for (const key of NODE_KEYS) {
    if (next[key] === 'process') next[key] = 'error'
  }
  return next
}

function eventLabel(eventName: string): string {
  const prefix = eventName.replace(/_(started|completed)$/, '')
  return NODE_LABELS[prefix] ?? prefix
}

export interface TaskRunValue {
  query: string
  setQuery: (value: string) => void
  running: boolean
  hasStarted: boolean
  aborted: boolean
  error: string | null
  dismissError: () => void
  taskId: string | null
  elapsed: number
  duration: number | null
  round: number
  log: LogEntry[]
  nodes: Record<string, StageStatus>
  plannerNotes: string[]
  chapterNotes: Record<number, string[]>
  chapterList: ChapterView[]
  writtenChapters: number
  retrievalSkipped: boolean
  plan: Plan | null
  outline: string[]
  sources: Source[]
  validation: Validation | null
  finalAnswer: string | null
  retrievedCount: number | null
  replans: number
  failedCount: number
  passedCount: number
  activeTab: string
  setActiveTab: (key: string) => void
  copied: boolean
  run: (overrideQuery?: string) => Promise<void>
  abort: () => void
  clear: () => void
  copy: () => Promise<void>
  download: () => void
}

const TaskRunContext = createContext<TaskRunValue | null>(null)

/**
 * 任务运行状态提升到 App 层：
 * 切换页面不再丢失进度，任务也不会因为离开页面而被中止。
 */
export function TaskRunProvider({ children }: { children: ReactNode }) {
  const [query, setQuery] = useState('')
  const [running, setRunning] = useState(false)
  const [hasStarted, setHasStarted] = useState(false)
  const [aborted, setAborted] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [nodes, setNodes] = useState<Record<NodeKey, StageStatus>>(INITIAL_NODES)
  const [plannerNotes, setPlannerNotes] = useState<string[]>([])
  const [chapterNotes, setChapterNotes] = useState<Record<number, string[]>>({})
  const [round, setRound] = useState(1)
  const [log, setLog] = useState<LogEntry[]>([])
  const [retrievalSkipped, setRetrievalSkipped] = useState(false)
  const [retrievedCount, setRetrievedCount] = useState<number | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [outline, setOutline] = useState<string[]>([])
  const [chapters, setChapters] = useState<Record<number, ChapterState>>({})
  const [validation, setValidation] = useState<Validation | null>(null)
  const [replans, setReplans] = useState(0)
  const [sources, setSources] = useState<Source[]>([])
  const [finalAnswer, setFinalAnswer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [duration, setDuration] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState('content')

  const startedAtRef = useRef<number | null>(null)
  const logIdRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const roundRef = useRef(1)

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => {
      if (startedAtRef.current !== null) {
        setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000))
      }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [running])

  const pushLog = useCallback(
    (label: string, message: string, tone: LogEntry['tone'] = 'info') => {
      logIdRef.current += 1
      const entry: LogEntry = { id: logIdRef.current, label, message, tone }
      setLog((prev) => [...prev, entry].slice(-MAX_LOG_ENTRIES))
    },
    [],
  )

  const addPlannerNote = useCallback((note: string) => {
    setPlannerNotes((prev) => [...prev, note].slice(-MAX_PLANNER_NOTES))
  }, [])

  const addChapterNote = useCallback((chapter: number, note: string) => {
    setChapterNotes((prev) => ({
      ...prev,
      [chapter]: [...(prev[chapter] ?? []), note].slice(-MAX_CHAPTER_NOTES_PER_CHAPTER),
    }))
  }, [])

  const updateChapter = useCallback((index: number, patch: Partial<ChapterState>) => {
    setChapters((prev) => ({
      ...prev,
      [index]: {
        written: prev[index]?.written ?? 0,
        writing: prev[index]?.writing ?? false,
        validation: prev[index]?.validation ?? 'pending',
        ...patch,
      },
    }))
  }, [])

  const handleEvent = useCallback(
    (event: TaskEvent) => {
      if (event.task_id) setTaskId(event.task_id)

      if (event.event === 'task_failed') {
        pushLog('失败', event.message, 'error')
        setNodes((prev) => markRunningAsError(prev))
        setError(event.message)
        setDuration(Math.floor((Date.now() - (startedAtRef.current ?? Date.now())) / 1000))
        return
      }

      if (event.event === 'task_completed') {
        pushLog('完成', '任务完成')
        setNodes({
          planner: 'finish',
          researcher: 'finish',
          outline: 'finish',
          writer: 'finish',
          validator: 'finish',
          summarizer: 'finish',
        })
        setFinalAnswer(event.result?.final_answer ?? '')
        setSources(event.result?.sources ?? [])
        if (event.result?.outline?.length) setOutline(event.result.outline)
        if (event.result?.validation) setValidation(event.result.validation)
        setReplans(event.result?.retry_count ?? 0)
        for (const target of event.result?.failed_chapters ?? []) {
          const n = chapterNumber(target)
          if (n !== null) updateChapter(n, { validation: 'failed' })
        }
        setDuration(Math.floor((Date.now() - (startedAtRef.current ?? Date.now())) / 1000))
        setActiveTab('content')
        return
      }

      if (event.event === 'retrying') {
        const isReplan = event.suggested_action === 'replan'
        pushLog('重试', event.message, 'warn')
        setNodes((prev) => ({ ...prev, validator: 'wait' }))

        if (isReplan) {
          // replan 是整轮回退：清空章节进度与旧提示，进入下一轮
          roundRef.current += 1
          setRound(roundRef.current)
          setChapters({})
          setChapterNotes({})
          addPlannerNote(`第 ${roundRef.current - 1} 轮：${event.message}`)
        } else {
          const n = chapterNumber(event.target)
          if (n !== null) addChapterNote(n, event.message)
        }

        if (event.exhausted) {
          const n = chapterNumber(event.target)
          if (n !== null) updateChapter(n, { validation: 'failed' })
        }
        return
      }

      const match =
        /^(planner|researcher|outline|writer|validator|summarizer)_(started|completed)$/.exec(
          event.event,
        )
      if (match) {
        const node = match[1] as NodeKey
        const phase = match[2]
        setNodes((prev) => ({ ...prev, [node]: phase === 'started' ? 'process' : 'finish' }))

        const chapterLabel = chapterNumber(event.step)
        const chapterSuffix = chapterLabel !== null ? `第 ${chapterLabel} 章 · ` : ''
        if (phase === 'completed' || node === 'researcher') {
          pushLog(
            eventLabel(event.event),
            `${chapterSuffix}${event.message}`,
            node === 'validator' && event.passed === false ? 'warn' : 'info',
          )
        }
      }

      if (event.event === 'planner_completed') {
        setPlan(event.plan ?? null)
        if (event.plan && !event.plan.needs_retrieval) {
          setRetrievalSkipped(true)
          setNodes((prev) => ({ ...prev, researcher: 'finish' }))
        }
      }
      if (event.event === 'researcher_completed') {
        setRetrievedCount(event.retrieved_count ?? 0)
        // 运行中即可展示「检索到的资料」（来自真实 metadata，已去重）
        if (event.sources) setSources(event.sources)
      }
      if (event.event === 'outline_completed') {
        const titles = event.outline ?? []
        setOutline(titles)
        setChapters(
          Object.fromEntries(
            titles.map((_, index) => [
              index + 1,
              { written: 0, writing: false, validation: 'pending' as ChapterValidation },
            ]),
          ),
        )
      }
      if (event.event === 'writer_started') {
        const n = chapterNumber(event.step)
        if (n !== null) updateChapter(n, { writing: true })
      }
      if (event.event === 'writer_completed') {
        const n = chapterNumber(event.step)
        if (n !== null) {
          setChapters((prev) => {
            const current = prev[n] ?? {
              written: 0,
              writing: false,
              validation: 'pending' as ChapterValidation,
            }
            return { ...prev, [n]: { ...current, written: current.written + 1, writing: false } }
          })
        }
      }
      if (event.event === 'validator_completed' && event.target?.startsWith('chapter_')) {
        const n = chapterNumber(event.target)
        if (n !== null) {
          updateChapter(n, { validation: event.passed ? 'passed' : 'failed' })
          if (event.passed) {
            // 已修正：清除该章的重写提示（完整历史仍可在「执行日志」查看）
            setChapterNotes((prev) => {
              if (prev[n] === undefined) return prev
              const next = { ...prev }
              delete next[n]
              return next
            })
          }
        }
      }
      if (event.event === 'validator_completed') {
        setValidation({
          passed: event.passed ?? false,
          issues: event.issues ?? [],
          suggested_action: event.suggested_action ?? '',
          target: event.target ?? 'document',
        })
      }
    },
    [addPlannerNote, addChapterNote, pushLog, updateChapter],
  )

  const clear = useCallback(() => {
    setHasStarted(false)
    setTaskId(null)
    setNodes(INITIAL_NODES)
    setPlannerNotes([])
    setChapterNotes({})
    roundRef.current = 1
    setRound(1)
    setLog([])
    logIdRef.current = 0
    setRetrievalSkipped(false)
    setRetrievedCount(null)
    setPlan(null)
    setOutline([])
    setChapters({})
    setValidation(null)
    setReplans(0)
    setSources([])
    setFinalAnswer(null)
    setCopied(false)
    setError(null)
    setElapsed(0)
    setDuration(null)
    setAborted(false)
    setActiveTab('content')
  }, [])

  const run = useCallback(
    async (overrideQuery?: string) => {
      const trimmed = (overrideQuery ?? query).trim()
      if (!trimmed || running) return
      // 预设任务「直接运行」路径：把预设写入输入框，保持界面与实际执行一致
      if (overrideQuery !== undefined && overrideQuery !== query) {
        setQuery(overrideQuery)
      }

      setRunning(true)
      clear()
      setHasStarted(true)
      startedAtRef.current = Date.now()
      const controller = new AbortController()
      abortRef.current = controller

      try {
        await streamTask(trimmed, handleEvent, controller.signal)
      } catch (err) {
        if ((err as { name?: string } | null)?.name === 'AbortError') {
          setAborted(true)
          setNodes(
            (prev) =>
              Object.fromEntries(
                Object.entries(prev).map(([key, value]) => [
                  key,
                  value === 'process' ? 'wait' : value,
                ]),
              ) as Record<NodeKey, StageStatus>,
          )
          pushLog('终止', '用户手动终止任务，连接已关闭（后端 Agent 同步取消）', 'warn')
        } else {
          setError(err instanceof ApiError ? err.message : '任务执行失败，请稍后重试')
          setNodes((prev) => markRunningAsError(prev))
        }
        setDuration(Math.floor((Date.now() - (startedAtRef.current ?? Date.now())) / 1000))
      } finally {
        abortRef.current = null
        setRunning(false)
      }
    },
    [clear, handleEvent, pushLog, query, running],
  )

  const abort = useCallback(() => {
    // 先请求后端取消（标记 cancelled 并中断模型调用），再关闭本地 SSE 流
    if (taskId) {
      void cancelTask(taskId).catch(() => {
        // 任务可能刚好结束/已被取消 -> 404，忽略
      })
    }
    abortRef.current?.abort()
  }, [taskId])

  const copy = useCallback(async () => {
    if (finalAnswer === null) return
    try {
      await navigator.clipboard.writeText(finalAnswer)
      setCopied(true)
    } catch {
      setError('复制失败（浏览器未授权剪贴板），请手动选择文本复制')
    }
  }, [finalAnswer])

  const download = useCallback(() => {
    if (finalAnswer === null) return
    // 文件名优先用任务目标，其次用用户输入，便于本地归档
    downloadMarkdown(finalAnswer, plan?.goal || query || 'agent-result')
  }, [finalAnswer, plan, query])

  const chapterList: ChapterView[] = outline.map((title, index) => {
    const state = chapters[index + 1]
    return {
      index: index + 1,
      title,
      written: state?.written ?? 0,
      writing: state?.writing ?? false,
      validation: state?.validation ?? 'pending',
    }
  })

  const writtenChapters = chapterList.filter((chapter) => chapter.written > 0).length
  const failedCount = chapterList.filter((chapter) => chapter.validation === 'failed').length
  const passedCount = chapterList.filter((chapter) => chapter.validation === 'passed').length

  const value: TaskRunValue = {
    query,
    setQuery,
    running,
    hasStarted,
    aborted,
    error,
    dismissError: () => setError(null),
    taskId,
    elapsed,
    duration,
    round,
    log,
    nodes,
    plannerNotes,
    chapterNotes,
    chapterList,
    writtenChapters,
    retrievalSkipped,
    plan,
    outline,
    sources,
    validation,
    finalAnswer,
    retrievedCount,
    replans,
    failedCount,
    passedCount,
    activeTab,
    setActiveTab,
    copied,
    run,
    abort,
    clear,
    copy,
    download,
  }

  return <TaskRunContext.Provider value={value}>{children}</TaskRunContext.Provider>
}

export function useTaskRun(): TaskRunValue {
  const context = useContext(TaskRunContext)
  if (context === null) {
    throw new Error('useTaskRun 必须在 TaskRunProvider 内部使用')
  }
  return context
}
