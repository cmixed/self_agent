import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import type {
  ChapterValidation,
  ChapterView,
  LogEntry,
  StageStatus,
} from '../components/AgentProgress'
import {
  ApiError,
  cancelTask,
  getTask,
  listTasks,
  streamObserve,
  streamRerun,
  streamResume,
  streamTask,
} from '../services/api'
import type {
  MemoryUpdates,
  OutputMode,
  Plan,
  RetrievalMode,
  Source,
  TaskDepth,
  TaskEvent,
  TaskProfile,
  TaskScope,
  TaskSummary,
  TokenUsage,
  Validation,
  VerbatimInfo,
  WritingBudget,
} from '../types/api'
import { downloadMarkdown } from '../utils/download'
import { clampPillSettings, readPillSettings, writePillSettings } from '../utils/pillSettings'
import type { PillSettings } from '../utils/pillSettings'
import {
  collectFinishedTasks,
  isTerminalStatus,
  loadAcknowledgedTasks,
  saveAcknowledgedTasks,
  splitPendingFinished,
} from '../utils/runningTasks'
import { useNav } from './nav'

/** 图中可能出现的节点（skills 仅在存在启用技能时挂载） */
const NODE_KEYS = [
  'answer',
  'planner',
  'researcher',
  'skills',
  'outline',
  'writer',
  'validator',
  'summarizer',
] as const
type NodeKey = (typeof NODE_KEYS)[number]

const INITIAL_NODES: Record<NodeKey, StageStatus> = {
  answer: 'wait',
  planner: 'wait',
  researcher: 'wait',
  skills: 'wait',
  outline: 'wait',
  writer: 'wait',
  validator: 'wait',
  summarizer: 'wait',
}

const NODE_LABELS: Record<string, string> = {
  answer: '回答',
  planner: '规划',
  researcher: '检索',
  skills: '技能',
  outline: '大纲',
  writer: '撰写',
  validator: '校验',
  summarizer: '整合',
  retrying: '重试',
  task_started: '开始',
  memory_started: '记忆',
  task_completed: '完成',
  task_failed: '失败',
  task_cancelled: '终止',
}

const MAX_LOG_ENTRIES = 60
// 提示条数兜底：后端预算（每章 ≤2 次重写 × ≤8 章 + ≤2 次 replan）已限制总量，
// 这里再加一层 UI 上限，避免任何异常情况下无限增长。
const MAX_PLANNER_NOTES = 4
const MAX_CHAPTER_NOTES_PER_CHAPTER = 3

/** 有任务在跑时的列表轮询间隔（毫秒）。 */
const RUNNING_POLL_MS = 5000
/** 轮询最近任务数：同时用于运行中胶囊与「完成待查看」差分。 */
const RECENT_TASKS_LIMIT = 20

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

function markRunningAsWait(nodes: Record<NodeKey, StageStatus>): Record<NodeKey, StageStatus> {
  const next = { ...nodes }
  for (const key of NODE_KEYS) {
    if (next[key] === 'process') next[key] = 'wait'
  }
  return next
}

function eventLabel(eventName: string): string {
  const prefix = eventName.replace(/_(started|completed)$/, '')
  return NODE_LABELS[prefix] ?? prefix
}

function isAbortError(error: unknown): boolean {
  return (error as { name?: string } | null)?.name === 'AbortError'
}

/** 任务集合签名：用于判断是否需要通知列表页刷新。 */
function taskSignature(tasks: readonly TaskSummary[]): string {
  return tasks
    .map((task) => task.task_id)
    .sort()
    .join(',')
}

export interface TaskRunValue {
  query: string
  setQuery: (value: string) => void
  /** 当前观察的任务是否仍在执行（后台其它任务不影响它） */
  running: boolean
  /** 服务端所有运行中任务（顶栏胶囊数据） */
  runningTasks: TaskSummary[]
  /** 已结束但用户还没查看的任务（顶栏常驻胶囊，刷新后仍保留） */
  finishedTasks: TaskSummary[]
  /** 关闭「完成待查看」胶囊（持久化，刷新后不再出现） */
  ackFinished: (taskId: string) => void
  /** 一次性把所有「完成待查看」胶囊标为已查看（不影响任务记录） */
  ackAllFinished: () => void
  /** 顶栏胶囊的可调参数（设置页维护，立即生效） */
  pillSettings: PillSettings
  /** 更新胶囊参数：写盘并立即按新上限裁剪待查看列表 */
  updatePillSettings: (patch: Partial<PillSettings>) => void
  /** 清除「已查看」记录：最近结束的任务会重新出现在胶囊里 */
  clearAcknowledged: () => void
  /** 任务状态变化信号：列表页 / 最近任务据此刷新 */
  tasksVersion: number
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
  skillNotes: string[]
  chapterNotes: Record<number, string[]>
  chapterList: ChapterView[]
  writtenChapters: number
  retrievalSkipped: boolean
  plan: Plan | null
  /** 本次长文的资料量自适应预算 */
  writingBudget: WritingBudget | null
  outline: string[]
  sources: Source[]
  validation: Validation | null
  finalAnswer: string | null
  retrievedCount: number | null
  /** 本次运行的模型用量（token / 缓存 / 速度）；旧记录为 null */
  usage: TokenUsage | null
  replans: number
  failedCount: number
  passedCount: number
  /** 本次任务的执行模式（direct / brief / longform），来自 task_started */
  mode: string | null
  profile: TaskProfile | null
  /** 用户选择的执行深度（仅影响新任务；续跑/重跑沿用原记录） */
  depth: TaskDepth
  setDepth: (depth: TaskDepth) => void
  useSkills: boolean
  setUseSkills: (value: boolean) => void
  /** 输出方式：正常生成 / 直接输出知识库原文（本次任务参数） */
  outputMode: OutputMode
  setOutputMode: (mode: OutputMode) => void
  /** 直接输出原文时指定的文档；null 表示自动选择 */
  verbatimDocumentId: string | null
  setVerbatimDocumentId: (documentId: string | null) => void
  /** 本次直接输出选中的文档（来自 verbatim_completed / 结果回显） */
  verbatim: VerbatimInfo | null
  /** 本次任务自动写入的长期记忆（来自 task_completed 结果） */
  memoryUpdates: MemoryUpdates | null
  activeTab: string
  setActiveTab: (key: string) => void
  copied: boolean
  run: (
    overrideQuery?: string,
    scope?: TaskScope | null,
    retrievalMode?: RetrievalMode,
    outputMode?: OutputMode,
    verbatimDocumentId?: string | null,
  ) => Promise<void>
  /** 本次运行实际使用的检索范围标签（来自事件/结果，仅用于展示） */
  scopeLabel: string | null
  /** 从断点继续（同一任务） */
  resume: (taskId: string) => Promise<void>
  /** 用原任务内容重新生成（新任务） */
  rerun: (taskId: string, sourceQuery: string) => Promise<void>
  /** 把工作台切换到某个任务（运行中则重建进度；已结束则回放终态） */
  selectTask: (taskId: string) => Promise<void>
  /** 终止任意运行中任务（活动任务会收到 task_cancelled 终态） */
  cancelRunning: (taskId: string) => Promise<void>
  abort: () => void
  clear: () => void
  copy: () => Promise<void>
  download: () => void
}

const TaskRunContext = createContext<TaskRunValue | null>(null)

/**
 * 任务运行状态提升到 App 层：
 * 切换页面不再丢失进度，刷新页面后也能通过后端事件通道重建进度。
 *
 * 观察模型：**同一时刻只观察一个任务**（工作台内容），但后端可以同时执行多个
 * 任务。切换观察对象只是断开旧订阅（不取消任务），顶栏胶囊负责展示与管理。
 */
export function TaskRunProvider({ children }: { children: ReactNode }) {
  const { page } = useNav()
  const [query, setQuery] = useState('')
  const [running, setRunning] = useState(false)
  const [runningTasks, setRunningTasks] = useState<TaskSummary[]>([])
  const [finishedTasks, setFinishedTasks] = useState<TaskSummary[]>([])
  const [pillSettings, setPillSettings] = useState<PillSettings>(readPillSettings)
  const [tasksVersion, setTasksVersion] = useState(0)
  const [hasStarted, setHasStarted] = useState(false)
  const [aborted, setAborted] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [nodes, setNodes] = useState<Record<NodeKey, StageStatus>>(INITIAL_NODES)
  const [plannerNotes, setPlannerNotes] = useState<string[]>([])
  const [skillNotes, setSkillNotes] = useState<string[]>([])
  const [scopeLabel, setScopeLabel] = useState<string | null>(null)
  const [chapterNotes, setChapterNotes] = useState<Record<number, string[]>>({})
  const [round, setRound] = useState(1)
  const [log, setLog] = useState<LogEntry[]>([])
  const [retrievalSkipped, setRetrievalSkipped] = useState(false)
  const [retrievedCount, setRetrievedCount] = useState<number | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [writingBudget, setWritingBudget] = useState<WritingBudget | null>(null)
  const [outline, setOutline] = useState<string[]>([])
  const [chapters, setChapters] = useState<Record<number, ChapterState>>({})
  const [validation, setValidation] = useState<Validation | null>(null)
  const [replans, setReplans] = useState(0)
  const [sources, setSources] = useState<Source[]>([])
  const [finalAnswer, setFinalAnswer] = useState<string | null>(null)
  const [usage, setUsage] = useState<TokenUsage | null>(null)
  const [mode, setMode] = useState<string | null>(null)
  const [profile, setProfile] = useState<TaskProfile | null>(null)
  const [depth, setDepth] = useState<TaskDepth>('auto')
  const [useSkills, setUseSkills] = useState(false)
  const [outputMode, setOutputMode] = useState<OutputMode>('generate')
  const [verbatimDocumentId, setVerbatimDocumentId] = useState<string | null>(null)
  const [verbatim, setVerbatim] = useState<VerbatimInfo | null>(null)
  const [memoryUpdates, setMemoryUpdates] = useState<MemoryUpdates | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [duration, setDuration] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState('content')

  const startedAtRef = useRef<number | null>(null)
  const finishedAtRef = useRef<string | null>(null)
  const logIdRef = useRef(0)
  /** 当前观察订阅的 AbortController（只影响订阅，不影响后端任务） */
  const observeRef = useRef<AbortController | null>(null)
  /** 观察令牌：每次 attach / detach 自增，旧流的迟到事件直接丢弃 */
  const generationRef = useRef(0)
  const activeTaskIdRef = useRef<string | null>(null)
  const hasStartedRef = useRef(false)
  const runningTasksRef = useRef<TaskSummary[]>([])
  const finishedTasksRef = useRef<TaskSummary[]>([])
  const pillSettingsRef = useRef(pillSettings)
  const tasksSignatureRef = useRef('')
  const acknowledgedRef = useRef<Set<string>>(new Set())
  const acknowledgedLoadedRef = useRef(false)
  const pageRef = useRef(page)
  const roundRef = useRef(1)

  useEffect(() => {
    pageRef.current = page
  }, [page])

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => {
      if (startedAtRef.current !== null) {
        setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000))
      }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [running])

  // --- 任务列表（顶栏胶囊 / 页面刷新联动） ---

  /** 懒加载「已确认（查看/关闭过）」的任务 id。 */
  const acknowledged = useCallback(() => {
    if (!acknowledgedLoadedRef.current) {
      acknowledgedLoadedRef.current = true
      acknowledgedRef.current = loadAcknowledgedTasks()
    }
    return acknowledgedRef.current
  }, [])

  /**
   * 标记任务已被用户查看（点击胶囊 / 关闭提醒 / 从其它入口打开）。
   *
   * 持久化到 localStorage，刷新页面后不再重复弹出完成态胶囊。
   */
  const acknowledgeTask = useCallback(
    (targetId: string) => {
      const ids = acknowledged()
      if (!ids.has(targetId)) {
        ids.add(targetId)
        saveAcknowledgedTasks(ids)
      }
      finishedTasksRef.current = finishedTasksRef.current.filter(
        (task) => task.task_id !== targetId,
      )
      setFinishedTasks((prev) => prev.filter((task) => task.task_id !== targetId))
    },
    [acknowledged],
  )

  /** 一次性把所有待查看胶囊标为已查看（批量已读）。 */
  const acknowledgeAllFinished = useCallback(() => {
    const ids = acknowledged()
    const pending = finishedTasksRef.current
    if (pending.length === 0) return
    for (const task of pending) ids.add(task.task_id)
    saveAcknowledgedTasks(ids)
    finishedTasksRef.current = []
    setFinishedTasks([])
  }, [acknowledged])

  /** 同一条任务再次运行（续跑）时，允许新的终态重新提醒。 */
  const forgetAcknowledged = useCallback(
    (targetId: string) => {
      const ids = acknowledged()
      if (ids.delete(targetId)) saveAcknowledgedTasks(ids)
    },
    [acknowledged],
  )

  /**
   * 按上限裁剪待查看列表；被裁掉的条目写入「已查看」。
   *
   * 失败任务由 `splitPendingFinished` 豁免，永远不会在这里被丢弃。
   */
  const trimFinished = useCallback(
    (list: TaskSummary[], limit: number) => {
      const { kept, dropped } = splitPendingFinished(list, limit)
      if (dropped.length > 0) {
        const ids = acknowledged()
        for (const task of dropped) ids.add(task.task_id)
        saveAcknowledgedTasks(ids)
      }
      return kept
    },
    [acknowledged],
  )

  /**
   * 合并服务端任务列表：运行中进胶囊；终态且用户未查看的进「完成待查看」。
   *
   * `restore` 只在启动首次加载时为 true，用于恢复刷新前未处理的完成任务
   * （限制条数与时间窗口，避免把陈年旧账翻出来）。
   */
  const applyTaskList = useCallback(
    (tasks: TaskSummary[], options: { restore?: boolean } = {}) => {
      const running = tasks.filter((task) => task.status === 'running')
      runningTasksRef.current = running
      setRunningTasks(running)

      const activeId = activeTaskIdRef.current
      const ids = acknowledged()
      // 正在工作台观察的任务：结果已经在眼前，视为已查看，不再弹常驻胶囊。
      // 离开了工作台则照常提醒（否则切页后完成的任务会被悄悄漏掉）。
      const observingFinished =
        activeId !== null &&
        pageRef.current === 'workspace' &&
        tasks.some((task) => task.task_id === activeId && isTerminalStatus(task.status))
      if (observingFinished && activeId && !ids.has(activeId)) {
        ids.add(activeId)
        saveAcknowledgedTasks(ids)
      }

      const collected = collectFinishedTasks({
        tasks,
        current: finishedTasksRef.current,
        acknowledged: ids,
        windowMs: pillSettingsRef.current.restoreWindowHours * 60 * 60 * 1000,
        limit: options.restore ? pillSettingsRef.current.restoreLimit : undefined,
      })
      // 会话内兜底：非失败任务最多保留用户设定的条数，更早的自动标为已查看
      //（失败任务不参与丢弃，红色提醒不能被静默吞掉）。
      const kept = trimFinished(collected, pillSettingsRef.current.pendingLimit)
      finishedTasksRef.current = kept
      setFinishedTasks(kept)

      const signature = `${taskSignature(running)}|${taskSignature(kept)}`
      if (signature !== tasksSignatureRef.current) {
        tasksSignatureRef.current = signature
        setTasksVersion((value) => value + 1)
      }
    },
    [acknowledged, trimFinished],
  )

  const refreshTasks = useCallback(
    async (options: { restore?: boolean } = {}) => {
      try {
        const data = await listTasks(RECENT_TASKS_LIMIT)
        applyTaskList(data.tasks, options)
      } catch {
        // 轮询失败静默：不影响正在观察的任务
      }
    },
    [applyTaskList],
  )

  /** 更新胶囊设置：写盘 + 立即按新的待查看上限裁剪当前列表。 */
  const updatePillSettings = useCallback(
    (patch: Partial<PillSettings>) => {
      const next = clampPillSettings({ ...pillSettingsRef.current, ...patch })
      pillSettingsRef.current = next
      setPillSettings(next)
      writePillSettings(next)
      const trimmed = trimFinished(finishedTasksRef.current, next.pendingLimit)
      finishedTasksRef.current = trimmed
      setFinishedTasks(trimmed)
    },
    [trimFinished],
  )

  /** 清除「已查看」记录，让最近结束的任务重新进入待查看（仍受上限与窗口约束）。 */
  const clearAcknowledged = useCallback(() => {
    const ids = acknowledged()
    ids.clear()
    saveAcknowledgedTasks(ids)
    void refreshTasks()
  }, [acknowledged, refreshTasks])

  const pushLog = useCallback((label: string, message: string, tone: LogEntry['tone'] = 'info') => {
    logIdRef.current += 1
    const entry: LogEntry = { id: logIdRef.current, label, message, tone }
    setLog((prev) => [...prev, entry].slice(-MAX_LOG_ENTRIES))
  }, [])

  const addSkillNote = useCallback((note: string) => {
    setSkillNotes((prev) => [...prev, note].slice(-MAX_PLANNER_NOTES))
  }, [])

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

  /**
   * 终态耗时：优先用服务的 finished_at（回放已结束任务时不能按「现在」算），
   * 其次用本地开始时间。
   */
  const finishDuration = useCallback(() => {
    const parsed = finishedAtRef.current ? Date.parse(finishedAtRef.current) : Number.NaN
    const end = Number.isNaN(parsed) ? Date.now() : parsed
    const start = startedAtRef.current ?? end
    setDuration(Math.max(0, Math.floor((end - start) / 1000)))
  }, [])

  const handleEvent = useCallback(
    (event: TaskEvent) => {
      if (event.task_id) {
        setTaskId(event.task_id)
        activeTaskIdRef.current = event.task_id
      }

      if (event.event === 'task_started') {
        if (event.mode) setMode(event.mode)
        if (event.profile) setProfile(event.profile)
        if (event.output_mode) setOutputMode(event.output_mode)
        if (event.retrieval_mode === 'none') setScopeLabel('不使用知识库')
        pushLog('开始', event.message, 'info')
        // 新任务立刻进入顶栏胶囊（不必等下一轮轮询）
        void refreshTasks()
        return
      }

      if (event.event === 'task_resumed') {
        if (event.mode) setMode(event.mode)
        if (event.profile) setProfile(event.profile)
        pushLog('继续', event.message, 'info')
        if (event.retrieval_mode === 'none') {
          setScopeLabel('不使用知识库')
          pushLog('范围', '沿用原设置：本次不使用知识库', 'info')
        } else if (event.scope?.label) {
          setScopeLabel(event.scope.label)
          pushLog('范围', `沿用原检索范围：${event.scope.label}`, 'info')
        }
        if (event.plan) {
          setPlan(event.plan)
          setNodes((prev) => ({ ...prev, planner: 'finish' }))
        }
        if (event.writing_budget) setWritingBudget(event.writing_budget)
        const titles = event.outline ?? []
        if (titles.length > 0) {
          const written = event.chapters_written ?? 0
          setOutline(titles)
          setChapters(
            Object.fromEntries(
              titles.map((_, index) => [
                index + 1,
                {
                  written: index < written ? 1 : 0,
                  writing: false,
                  validation: 'pending' as ChapterValidation,
                },
              ]),
            ),
          )
          setNodes((prev) => ({ ...prev, outline: 'finish', writer: 'process' }))
        }
        if (event.sources) {
          setSources(event.sources)
          setRetrievedCount(event.retrieved_count ?? event.sources.length)
          setNodes((prev) => ({ ...prev, researcher: 'finish', skills: 'finish' }))
        }
        return
      }

      if (event.event === 'verbatim_started') {
        setNodes((prev) => ({ ...prev, researcher: 'process' }))
        pushLog('原文', event.message, 'info')
        return
      }

      if (event.event === 'verbatim_selected') {
        setNodes((prev) => ({ ...prev, researcher: 'finish', summarizer: 'process' }))
        setVerbatim({
          document_id: event.document_id ?? '',
          filename: event.filename ?? '',
          title: event.title ?? '',
          chars: 0,
          selection: event.selection ?? '',
          reason: event.reason ?? '',
        })
        pushLog('原文', event.message, 'info')
        return
      }

      if (event.event === 'verbatim_completed') {
        setNodes((prev) => ({ ...prev, researcher: 'finish', summarizer: 'finish' }))
        setVerbatim({
          document_id: event.document_id ?? '',
          filename: event.filename ?? '',
          title: event.title ?? '',
          chars: event.chars ?? 0,
          selection: event.selection ?? '',
          reason: event.reason ?? '',
        })
        pushLog('原文', event.message, 'info')
        return
      }

      if (event.event === 'memory_started') {
        pushLog('记忆', event.message, 'info')
        return
      }

      if (event.event === 'memory_updated') {
        if (event.memory_updates) setMemoryUpdates(event.memory_updates)
        pushLog('记忆', event.message || '已更新长期记忆', 'info')
        return
      }

      if (event.event === 'task_failed') {
        pushLog('失败', event.message, 'error')
        setNodes((prev) => markRunningAsError(prev))
        setError(event.message)
        finishDuration()
        return
      }

      if (event.event === 'task_cancelled') {
        pushLog('终止', event.message || '任务已被终止', 'warn')
        setNodes((prev) => markRunningAsError(prev))
        setAborted(true)
        finishDuration()
        return
      }

      if (event.event === 'task_completed') {
        pushLog('完成', '任务完成')
        setNodes({
          answer: 'finish',
          planner: 'finish',
          researcher: 'finish',
          skills: 'finish',
          outline: 'finish',
          writer: 'finish',
          validator: 'finish',
          summarizer: 'finish',
        })
        if (event.result?.mode) setMode(event.result.mode)
        if (event.result?.profile) setProfile(event.result.profile)
        if (event.result?.output_mode) setOutputMode(event.result.output_mode)
        setVerbatim(event.result?.verbatim ?? null)
        setMemoryUpdates(event.result?.memory_updates ?? null)
        setWritingBudget(event.result?.writing_budget ?? null)
        setFinalAnswer(event.result?.final_answer ?? '')
        setUsage(event.result?.usage ?? null)
        setSources(event.result?.sources ?? [])
        if (event.result?.outline?.length) setOutline(event.result.outline)
        if (event.result?.validation) setValidation(event.result.validation)
        setReplans(event.result?.retry_count ?? 0)
        if (event.result?.retrieval_mode === 'none') setScopeLabel('不使用知识库')
        else if (event.result?.scope?.label) setScopeLabel(event.result.scope.label)
        for (const target of event.result?.failed_chapters ?? []) {
          const n = chapterNumber(target)
          if (n !== null) updateChapter(n, { validation: 'failed' })
        }
        finishDuration()
        setActiveTab('content')
        // 任务已生成完毕：长期记忆提取是终态之后的副作用，不应让界面继续显示「运行中」
        setRunning(false)
        void refreshTasks()
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

      if (event.event === 'skill_started' || event.event === 'skill_completed') {
        const finished = event.event === 'skill_completed'
        setNodes((prev) => ({ ...prev, skills: finished ? 'finish' : 'process' }))
        if (finished) {
          const name = event.skill_name || '技能'
          addSkillNote(`${name}：${event.summary || '执行完成'}`)
          pushLog('技能', `${name} 执行完成`, 'info')
        } else {
          pushLog('技能', event.message, 'info')
        }
        return
      }

      const match =
        /^(answer|planner|researcher|skills|outline|writer|validator|summarizer)_(started|completed)$/.exec(
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
        if (event.writing_budget) setWritingBudget(event.writing_budget)
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
    [
      addPlannerNote,
      addSkillNote,
      addChapterNote,
      pushLog,
      updateChapter,
      finishDuration,
      refreshTasks,
    ],
  )

  /** 只重置展示状态，不触碰订阅（clear / 开始新运行共用）。 */
  const resetDisplay = useCallback(() => {
    setHasStarted(false)
    hasStartedRef.current = false
    setTaskId(null)
    activeTaskIdRef.current = null
    setNodes(INITIAL_NODES)
    setPlannerNotes([])
    setSkillNotes([])
    setScopeLabel(null)
    setChapterNotes({})
    roundRef.current = 1
    setRound(1)
    setLog([])
    logIdRef.current = 0
    setRetrievalSkipped(false)
    setRetrievedCount(null)
    setPlan(null)
    setWritingBudget(null)
    setOutline([])
    setChapters({})
    setValidation(null)
    setReplans(0)
    setSources([])
    setFinalAnswer(null)
    setUsage(null)
    setMode(null)
    setProfile(null)
    setVerbatim(null)
    setMemoryUpdates(null)
    setCopied(false)
    setError(null)
    setElapsed(0)
    setDuration(null)
    setAborted(false)
    setActiveTab('content')
  }, [])

  /** 断开当前订阅（不取消后端任务），并让后续迟到事件失效。 */
  const detach = useCallback(() => {
    generationRef.current += 1
    observeRef.current?.abort()
    observeRef.current = null
    setRunning(false)
  }, [])

  const clear = useCallback(() => {
    detach()
    resetDisplay()
    // 新建任务时旧任务仍在后台跑：立即刷新一次，让胶囊无需等待下一轮轮询
    void refreshTasks()
  }, [detach, refreshTasks, resetDisplay])

  /** 订阅一个已有任务：回放缓冲区 + 跟随实时事件。 */
  const attachTask = useCallback(
    async (task: Pick<TaskSummary, 'task_id' | 'query'> & Partial<TaskSummary>) => {
      generationRef.current += 1
      const generation = generationRef.current
      observeRef.current?.abort()
      const controller = new AbortController()
      observeRef.current = controller

      resetDisplay()
      setHasStarted(true)
      hasStartedRef.current = true
      setTaskId(task.task_id)
      activeTaskIdRef.current = task.task_id
      setQuery(task.query)
      if (task.mode) setMode(task.mode)
      setOutputMode(task.mode === 'verbatim' ? 'verbatim' : 'generate')
      const start = task.created_at ? Date.parse(task.created_at) : Number.NaN
      startedAtRef.current = Number.isNaN(start) ? Date.now() : start
      finishedAtRef.current = task.finished_at ?? null
      setElapsed(Math.max(0, Math.floor((Date.now() - startedAtRef.current) / 1000)))
      setRunning(true)

      try {
        await streamObserve(
          task.task_id,
          (event) => {
            // 观察对象已切换：旧流的迟到事件直接丢弃，避免状态串台
            if (generationRef.current !== generation) return
            handleEvent(event)
          },
          controller.signal,
        )
      } catch (err) {
        if (generationRef.current !== generation || isAbortError(err)) return
        setError(err instanceof ApiError ? err.message : '无法读取任务进度，请稍后重试')
      } finally {
        if (generationRef.current === generation) {
          observeRef.current = null
          setRunning(false)
        }
        void refreshTasks()
      }
    },
    [handleEvent, refreshTasks, resetDisplay],
  )

  /** 公共执行体：复位状态 + 消费一条 SSE 流（新建 / 续跑 / 重跑共用）。 */
  const runStream = useCallback(
    async (start: (onEvent: (event: TaskEvent) => void, signal: AbortSignal) => Promise<void>) => {
      generationRef.current += 1
      const generation = generationRef.current
      observeRef.current?.abort()
      const controller = new AbortController()
      observeRef.current = controller

      resetDisplay()
      setHasStarted(true)
      hasStartedRef.current = true
      startedAtRef.current = Date.now()
      finishedAtRef.current = null
      setRunning(true)

      try {
        await start((event) => {
          // 已切换到别的观察对象：旧流的迟到事件直接丢弃
          if (generationRef.current !== generation) return
          handleEvent(event)
        }, controller.signal)
      } catch (err) {
        // 已切换到别的观察对象：本地状态由新观察者接管，不再写入
        if (generationRef.current !== generation) return
        if (isAbortError(err)) {
          setAborted(true)
          setNodes((prev) => markRunningAsWait(prev))
          pushLog('终止', '用户手动终止任务，连接已关闭（后端 Agent 同步取消）', 'warn')
        } else {
          setError(err instanceof ApiError ? err.message : '任务执行失败，请稍后重试')
          setNodes((prev) => markRunningAsError(prev))
        }
        finishDuration()
      } finally {
        if (generationRef.current === generation) {
          observeRef.current = null
          setRunning(false)
        }
        void refreshTasks()
      }
    },
    [finishDuration, handleEvent, pushLog, refreshTasks, resetDisplay],
  )

  const run = useCallback(
    async (
      overrideQuery?: string,
      scope?: TaskScope | null,
      retrievalMode: RetrievalMode = 'all',
      modeOverride?: OutputMode,
      verbatimOverride?: string | null,
    ) => {
      const trimmed = (overrideQuery ?? query).trim()
      if (!trimmed) return
      const effectiveOutput = modeOverride ?? outputMode
      const effectiveDocument =
        verbatimOverride !== undefined ? verbatimOverride : verbatimDocumentId
      // 预设任务「直接运行」路径：把预设写入输入框，保持界面与实际执行一致
      if (overrideQuery !== undefined && overrideQuery !== query) {
        setQuery(overrideQuery)
      }
      await runStream((onEvent, signal) =>
        streamTask(
          trimmed,
          onEvent,
          signal,
          scope,
          depth,
          useSkills,
          retrievalMode,
          effectiveOutput,
          effectiveDocument,
        ),
      )
    },
    [depth, outputMode, query, runStream, setQuery, useSkills, verbatimDocumentId],
  )

  const resume = useCallback(
    async (taskId: string) => {
      // 续跑复用同一 task_id：清掉旧的「已查看」标记，新的结果仍能提醒
      forgetAcknowledged(taskId)
      await runStream((onEvent, signal) => streamResume(taskId, onEvent, signal))
    },
    [forgetAcknowledged, runStream],
  )

  const rerun = useCallback(
    async (taskId: string, sourceQuery: string) => {
      setQuery(sourceQuery)
      await runStream((onEvent, signal) => streamRerun(taskId, onEvent, signal))
    },
    [runStream, setQuery],
  )

  /** 切换到某个任务：运行中则重建进度，已结束则回放终态事件。 */
  const selectTask = useCallback(
    async (targetId: string) => {
      const known =
        runningTasksRef.current.find((task) => task.task_id === targetId) ??
        finishedTasksRef.current.find((task) => task.task_id === targetId)
      if (known) {
        // 打开已结束任务 = 已查看：常驻胶囊随之消失（运行中任务不标记）
        if (isTerminalStatus(known.status)) acknowledgeTask(targetId)
        await attachTask(known)
        return
      }
      try {
        const detail = await getTask(targetId)
        if (isTerminalStatus(detail.status)) acknowledgeTask(targetId)
        await attachTask(detail)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : '无法打开该任务的实时进度')
      }
    },
    [acknowledgeTask, attachTask],
  )

  /** 终止任意任务；活动任务会收到后端推送的 task_cancelled 终态。 */
  const cancelRunning = useCallback(
    async (targetId: string) => {
      try {
        await cancelTask(targetId)
      } catch {
        // 任务可能刚好结束 / 已被取消（404），视为已终止
      }
      await refreshTasks()
    },
    [refreshTasks],
  )

  const abort = useCallback(() => {
    // 先请求后端取消（标记 cancelled 并中断模型调用），再关闭本地订阅
    if (activeTaskIdRef.current) {
      void cancelTask(activeTaskIdRef.current).catch(() => {
        // 任务可能刚好结束/已被取消 -> 404，忽略
      })
    }
    generationRef.current += 1
    observeRef.current?.abort()
    observeRef.current = null
    setRunning(false)
    setAborted(true)
    setNodes((prev) => markRunningAsWait(prev))
    pushLog('终止', '用户手动终止任务，后端 Agent 已同步取消', 'warn')
    finishDuration()
    void refreshTasks()
  }, [finishDuration, pushLog, refreshTasks])

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

  // 启动恢复：刷新页面后自动接上最近一个正在执行的任务（与未刷新时一致），
  // 并恢复未查看的「完成」胶囊；之后按固定间隔刷新最近任务列表
  // （其它标签页 / 刷新前启动的任务）。
  useEffect(() => {
    let stopped = false
    let restore = true
    const load = async (attachIfIdle: boolean) => {
      const generation = generationRef.current
      try {
        const data = await listTasks(RECENT_TASKS_LIMIT)
        if (stopped) return
        applyTaskList(data.tasks, { restore })
        restore = false
        const running = data.tasks.filter((task) => task.status === 'running')
        // 只在「用户还没开始任何任务」且期间没有被新运行占用时恢复
        if (attachIfIdle && running.length > 0 && !hasStartedRef.current) {
          if (generationRef.current !== generation) return
          await attachTask(running[0])
        }
      } catch {
        // 启动恢复失败静默：不阻塞工作台
      }
    }
    void load(true)
    const timer = window.setInterval(() => void load(false), RUNNING_POLL_MS)
    return () => {
      stopped = true
      window.clearInterval(timer)
      // 卸载（应用关闭 / 测试清理）：断开订阅，但后端任务继续执行
      observeRef.current?.abort()
      observeRef.current = null
    }
  }, [applyTaskList, attachTask])

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
    runningTasks,
    finishedTasks,
    ackFinished: acknowledgeTask,
    ackAllFinished: acknowledgeAllFinished,
    pillSettings,
    updatePillSettings,
    clearAcknowledged,
    tasksVersion,
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
    skillNotes,
    chapterNotes,
    chapterList,
    writtenChapters,
    retrievalSkipped,
    plan,
    writingBudget,
    outline,
    sources,
    validation,
    finalAnswer,
    retrievedCount,
    usage,
    replans,
    failedCount,
    passedCount,
    mode,
    profile,
    depth,
    setDepth,
    useSkills,
    setUseSkills,
    outputMode,
    setOutputMode,
    verbatimDocumentId,
    setVerbatimDocumentId,
    verbatim,
    memoryUpdates,
    activeTab,
    setActiveTab,
    copied,
    run,
    scopeLabel,
    resume,
    rerun,
    selectTask,
    cancelRunning,
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
