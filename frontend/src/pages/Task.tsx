import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Input,
  Result,
  Row,
  Space,
  Statistic,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useEffect, useRef, useState } from 'react'

import AgentProgress from '../components/AgentProgress'
import type {
  ChapterValidation,
  ChapterView,
  LogEntry,
  MacroStage,
  StageStatus,
} from '../components/AgentProgress'
import PageContainer from '../components/PageContainer'
import MarkdownView from '../components/MarkdownView'
import { ApiError, cancelTask, streamTask } from '../services/api'
import type { Plan, Source, TaskEvent, Validation } from '../types/api'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const PAGE_TITLE = '任务'
const PAGE_DESCRIPTION = '提交一个复杂任务：Agent 会先规划、再检索你的资料、分章节撰写并自我校验。'
const PAGE_MAX_WIDTH = 1080

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

const SAMPLE_TASKS = [
  '根据我的资料写一篇 RAG 技术综述',
  '总结我的资料里关于文本切分的要点',
  '对比向量检索与关键词检索的差异',
]

const TARGET_LABEL = (target: string) =>
  target === 'document' ? '整篇文档' : `章节 ${target.replace('chapter_', '')}`

const chapterNumber = (value: string | null | undefined): number | null => {
  const match = /^chapter_(\d+)$/.exec(value ?? '')
  return match ? Number(match[1]) : null
}

const MAX_LOG_ENTRIES = 60

function markRunningAsError(nodes: Record<NodeKey, StageStatus>): Record<NodeKey, StageStatus> {
  const next = { ...nodes }
  for (const key of NODE_KEYS) {
    if (next[key] === 'process') next[key] = 'error'
  }
  return next
}

interface ChapterState {
  written: number
  writing: boolean
  validation: ChapterValidation
}

function eventLabel(eventName: string): string {
  const prefix = eventName.replace(/_(started|completed)$/, '')
  return NODE_LABELS[prefix] ?? prefix
}

export default function TaskPage() {
  const [query, setQuery] = useState('')
  const [running, setRunning] = useState(false)
  const [hasStarted, setHasStarted] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [nodes, setNodes] = useState<Record<NodeKey, StageStatus>>(INITIAL_NODES)
  const [stageNotes, setStageNotes] = useState<Record<string, string[]>>({})
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
  const [aborted, setAborted] = useState(false)

  const startedAtRef = useRef<number | null>(null)
  const logIdRef = useRef(0)
  const resultRef = useRef<HTMLDivElement | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // 卸载（切换页面）时中止流，避免 Agent 在后台继续跑
  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => {
      if (startedAtRef.current !== null) {
        setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000))
      }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [running])

  useEffect(() => {
    if (finalAnswer !== null) {
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [finalAnswer])

  const pushLog = (label: string, message: string, tone: LogEntry['tone'] = 'info') => {
    logIdRef.current += 1
    const entry: LogEntry = { id: logIdRef.current, label, message, tone }
    setLog((prev) => [...prev, entry].slice(-MAX_LOG_ENTRIES))
  }

  const addNote = (stage: string, note: string) => {
    setStageNotes((prev) => ({ ...prev, [stage]: [...(prev[stage] ?? []), note] }))
  }

  const updateChapter = (index: number, patch: Partial<ChapterState>) => {
    setChapters((prev) => ({
      ...prev,
      [index]: {
        written: prev[index]?.written ?? 0,
        writing: prev[index]?.writing ?? false,
        validation: prev[index]?.validation ?? 'pending',
        ...patch,
      },
    }))
  }

  const handleEvent = (event: TaskEvent) => {
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
        // replan 是整轮回退：清空章节进度并进入下一轮，避免"莫名跳回去"
        setRound((prev) => prev + 1)
        setChapters({})
        addNote('planner', `第 ${round} 轮：${event.message}`)
      } else {
        addNote('chapters', event.message)
      }

      if (event.exhausted) {
        const n = chapterNumber(event.target)
        if (n !== null) updateChapter(n, { validation: 'failed' })
      }
      return
    }

    // 其余节点事件
    const match = /^(planner|researcher|outline|writer|validator|summarizer)_(started|completed)$/.exec(
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
          const current = prev[n] ?? { written: 0, writing: false, validation: 'pending' as const }
          return { ...prev, [n]: { ...current, written: current.written + 1, writing: false } }
        })
      }
    }
    if (event.event === 'validator_completed' && event.target?.startsWith('chapter_')) {
      const n = chapterNumber(event.target)
      if (n !== null) updateChapter(n, { validation: event.passed ? 'passed' : 'failed' })
    }
    if (event.event === 'validator_completed') {
      setValidation({
        passed: event.passed ?? false,
        issues: event.issues ?? [],
        suggested_action: event.suggested_action ?? '',
        target: event.target ?? 'document',
      })
    }
  }

  const handleCopy = async () => {
    if (finalAnswer === null) return
    try {
      await navigator.clipboard.writeText(finalAnswer)
      setCopied(true)
    } catch {
      setError('复制失败（浏览器未授权剪贴板），请手动选择文本复制')
    }
  }

  const handleDownload = () => {
    if (finalAnswer === null) return
    const blob = new Blob([finalAnswer], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `agent-result-${Date.now()}.md`
    link.click()
    URL.revokeObjectURL(url)
  }

  const reset = () => {
    setHasStarted(false)
    setTaskId(null)
    setNodes(INITIAL_NODES)
    setStageNotes({})
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
    setActiveTab('content')
    setAborted(false)
  }

  const handleRun = async () => {
    const trimmed = query.trim()
    if (!trimmed || running) return

    setRunning(true)
    reset()
    setHasStarted(true)
    startedAtRef.current = Date.now()
    const controller = new AbortController()
    abortRef.current = controller

    try {
      await streamTask(trimmed, handleEvent, controller.signal)
    } catch (err) {
      if ((err as { name?: string } | null)?.name === 'AbortError') {
        // 用户主动终止：不是错误，保留已完成的进度
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
  }

  const handleAbort = () => {
    // 先请求后端取消（把该运行标记为 cancelled 并中断模型调用），再关闭本地 SSE 流
    if (taskId) {
      void cancelTask(taskId).catch(() => {
        // 任务可能刚好结束/已被取消 -> 404，忽略即可
      })
    }
    abortRef.current?.abort()
  }

  // --- 进度视图：宏观 5 阶段，其中「逐章撰写与校验」按章节展开 -----------------
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

  const chapterStageStatus = (): StageStatus => {
    if (nodes.writer === 'error' || nodes.validator === 'error') return 'error'
    if (nodes.writer === 'process' || nodes.validator === 'process') return 'process'
    if (nodes.writer === 'finish' && nodes.validator === 'finish') return 'finish'
    return 'wait'
  }

  const macroStages: MacroStage[] = [
    {
      key: 'planner',
      title: '分析任务并生成计划',
      status: nodes.planner,
      badge: replans > 0 ? <Tag color="volcano">重新规划 {replans} 次</Tag> : undefined,
      notes: stageNotes.planner,
    },
    {
      key: 'researcher',
      title: '检索个人知识库',
      status: nodes.researcher,
      skipped: retrievalSkipped,
      badge:
        !retrievalSkipped && retrievedCount !== null ? (
          <Tag color={retrievedCount > 0 ? 'blue' : 'orange'}>{retrievedCount} 条片段</Tag>
        ) : undefined,
    },
    {
      key: 'outline',
      title: '生成文章大纲',
      status: nodes.outline,
      badge: outline.length > 0 ? <Tag>{outline.length} 章</Tag> : undefined,
    },
    {
      key: 'chapters',
      title: '逐章撰写与校验',
      status: chapterStageStatus(),
      note: outline.length > 0 ? `已写 ${writtenChapters}/${outline.length} 章` : undefined,
      progress: outline.length > 0 ? { done: writtenChapters, total: outline.length } : undefined,
      chapters: chapterList,
      notes: stageNotes.chapters,
    },
    {
      key: 'summarizer',
      title: '整合最终结果',
      status: nodes.summarizer,
      badge: finalAnswer !== null ? <Tag color="green">已整合</Tag> : undefined,
    },
  ]

  const tabItems = [
    {
      key: 'overview',
      label: '概览',
      children: (
        <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
          <Row gutter={[16, 16]}>
            <Col xs={12} lg={6}>
              <Statistic title="章节数" value={outline.length} />
            </Col>
            <Col xs={12} lg={6}>
              <Statistic title="命中片段" value={retrievedCount ?? 0} />
            </Col>
            <Col xs={12} lg={6}>
              <Statistic title="重新规划" value={replans} suffix="次" />
            </Col>
            <Col xs={12} lg={6}>
              <Statistic title="执行耗时" value={duration ?? elapsed} suffix="秒" />
            </Col>
          </Row>

          {failedCount > 0 && (
            <Alert
              type="warning"
              showIcon
              title={`有 ${failedCount} 个章节已达重试上限、未通过校验`}
              description="这些章节在正文中以「未通过校验」标注，其余章节正常产出。"
            />
          )}

          {validation && (
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="校验对象">
                {TARGET_LABEL(validation.target)}
              </Descriptions.Item>
              <Descriptions.Item label="校验结论">
                <Tag color={validation.passed ? 'green' : 'red'}>
                  {validation.passed ? '通过' : '未通过'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="章节情况">
                共 {outline.length} 章：通过 {passedCount} 章
                {failedCount > 0 ? `，未通过 ${failedCount} 章` : ''}
              </Descriptions.Item>
              {taskId && (
                <Descriptions.Item label="任务 ID">
                  <Text code copyable>
                    {taskId}
                  </Text>
                </Descriptions.Item>
              )}
            </Descriptions>
          )}
        </Space>
      ),
    },
    {
      key: 'content',
      label: '正文',
      children: finalAnswer ? (
        <MarkdownView content={finalAnswer} />
      ) : (
        <Text type="secondary">尚未生成正文</Text>
      ),
    },
    {
      key: 'chapters',
      label: '章节',
      children:
        chapterList.length > 0 ? (
          <ol className="plain-list">
            {chapterList.map((chapter) => (
              <li key={chapter.index}>
                <Tag
                  color={
                    chapter.validation === 'passed'
                      ? 'green'
                      : chapter.validation === 'failed'
                        ? 'red'
                        : chapter.written > 0
                          ? 'blue'
                          : 'default'
                  }
                >
                  {chapter.validation === 'passed'
                    ? '通过'
                    : chapter.validation === 'failed'
                      ? '未通过'
                      : chapter.written > 0
                        ? `已写 ×${chapter.written}`
                        : '待写'}
                </Tag>
                {chapter.title}
              </li>
            ))}
          </ol>
        ) : (
          <Empty description="尚未生成大纲" />
        ),
    },
    {
      key: 'plan',
      label: '计划',
      children: plan ? (
        <Space orientation="vertical" size="small" style={{ width: '100%' }}>
          <Paragraph style={{ marginBottom: 0 }}>
            <Text strong>目标：</Text>
            {plan.goal}
          </Paragraph>
          <Paragraph style={{ marginBottom: 0 }}>
            <Text strong>需要知识库检索：</Text>
            <Tag color={plan.needs_retrieval ? 'blue' : 'default'}>
              {plan.needs_retrieval ? '需要' : '不需要'}
            </Tag>
          </Paragraph>
          <ol className="plain-list">
            {plan.steps.map((step) => (
              <li key={step.id}>
                <Tag>{step.type}</Tag>
                {step.description}
              </li>
            ))}
          </ol>
        </Space>
      ) : (
        <Empty description="尚未生成计划" />
      ),
    },
    {
      key: 'validation',
      label: '校验',
      children: validation ? (
        <Space orientation="vertical" size="small" style={{ width: '100%' }}>
          <div>
            <Text strong>结论：</Text>
            <Tag color={validation.passed ? 'green' : 'red'}>
              {validation.passed ? '通过' : '未通过'}
            </Tag>
            <Text type="secondary">（{TARGET_LABEL(validation.target)}）</Text>
          </div>
          {validation.issues.length > 0 ? (
            <ul className="plain-list">
              {validation.issues.map((issue, index) => (
                <li key={index}>
                  <Text type="warning">{issue}</Text>
                </li>
              ))}
            </ul>
          ) : (
            <Text type="secondary">没有发现问题</Text>
          )}
        </Space>
      ) : (
        <Empty description="尚未执行校验" />
      ),
    },
    {
      key: 'sources',
      label: `来源${sources.length > 0 ? `（${sources.length}）` : ''}`,
      children:
        sources.length > 0 ? (
          <ol className="plain-list">
            {sources.map((source) => (
              <li key={source.chunk_id}>
                <Text>
                  [{source.index}] {source.filename}
                  {source.page ? `（第 ${source.page} 页）` : ''}
                </Text>
                {typeof source.score === 'number' && (
                  <Tag style={{ marginLeft: 8 }}>相似度 {source.score.toFixed(3)}</Tag>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <Empty description="本次任务未使用知识库来源（可能计划不需要检索，或知识库为空）" />
        ),
    },
  ]

  return (
    <PageContainer
      title={PAGE_TITLE}
      description={PAGE_DESCRIPTION}
      maxWidth={PAGE_MAX_WIDTH}
      extra={running ? <Tag color="processing">运行中</Tag> : null}
    >
      <Card title="提交任务">
        <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
          <TextArea
            id="task-query"
            name="query"
            autoSize={{ minRows: 3, maxRows: 8 }}
            value={query}
            disabled={running}
            placeholder="例如：根据我的资料写一篇 RAG 技术综述"
            onChange={(event) => setQuery(event.target.value)}
          />
          <div className="composer-actions">
            <Space size={[8, 8]} wrap>
              <Text type="secondary">示例：</Text>
              {SAMPLE_TASKS.map((sample) => (
                <Tag
                  key={sample}
                  className="sample-tag"
                  onClick={() => {
                    if (!running) setQuery(sample)
                  }}
                >
                  {sample}
                </Tag>
              ))}
            </Space>
            <Space>
              {running ? (
                <Button danger onClick={handleAbort}>
                  终止任务
                </Button>
              ) : (
                <Button type="primary" onClick={() => void handleRun()}>
                  运行任务
                </Button>
              )}
              <Button
                disabled={running}
                onClick={() => {
                  setQuery('')
                  reset()
                }}
              >
                清空
              </Button>
            </Space>
          </div>
        </Space>
      </Card>

      <Card title="执行进度">
        <AgentProgress
          stages={macroStages}
          elapsedSeconds={elapsed}
          running={running}
          hasStarted={hasStarted}
          round={round}
          log={log}
        />
      </Card>

      {aborted && (
        <Alert
          type="warning"
          showIcon
          title="任务已终止"
          description="已关闭与后端的连接，Agent 会同步取消，不会继续消耗模型调用。已生成的计划 / 大纲 / 章节进度保留在上方。注意：正文只在任务正常完成时返回，因此终止后无法查看已写章节的正文；任务历史中该记录会停留在「运行中」状态。"
        />
      )}

      {error && (
        <Result
          status="error"
          title="任务未能完成"
          subTitle={error}
          extra={
            <Button type="primary" onClick={() => void handleRun()} disabled={running}>
              重试
            </Button>
          }
        />
      )}

      {finalAnswer !== null && (
        <div ref={resultRef}>
          <Card
            title="执行结果"
            extra={
              <Space>
                <Tooltip title="复制 Markdown 原文">
                  <Button size="small" onClick={() => void handleCopy()}>
                    {copied ? '已复制' : '复制'}
                  </Button>
                </Tooltip>
                <Button size="small" onClick={handleDownload}>
                  下载 .md
                </Button>
              </Space>
            }
          >
            <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
          </Card>
        </div>
      )}
    </PageContainer>
  )
}
