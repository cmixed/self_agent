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
import type { StageStatus, StageView } from '../components/AgentProgress'
import PageContainer from '../components/PageContainer'
import MarkdownView from '../components/MarkdownView'
import { ApiError, streamTask } from '../services/api'
import type { Plan, Source, TaskEvent, Validation } from '../types/api'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const PAGE_TITLE = '任务'
const PAGE_DESCRIPTION = '提交一个复杂任务：Agent 会先规划、再检索你的资料、分章节撰写并自我校验。'
const PAGE_MAX_WIDTH = 1080

const STAGE_ORDER = ['planner', 'researcher', 'outline', 'writer', 'validator', 'summarizer'] as const
type StageKey = (typeof STAGE_ORDER)[number]

const STAGE_TITLES: Record<StageKey, string> = {
  planner: '分析任务并生成计划',
  researcher: '检索个人知识库',
  outline: '生成文章大纲',
  writer: '逐章撰写内容',
  validator: '校验内容质量',
  summarizer: '整合最终结果',
}

const INITIAL_STAGES: Record<StageKey, StageStatus> = {
  planner: 'wait',
  researcher: 'wait',
  outline: 'wait',
  writer: 'wait',
  validator: 'wait',
  summarizer: 'wait',
}

const SAMPLE_TASKS = [
  '根据我的资料写一篇 RAG 技术综述',
  '总结我的资料里关于文本切分的要点',
  '对比向量检索与关键词检索的差异',
]

const TARGET_LABEL = (target: string) =>
  target === 'document' ? '整篇文档' : `章节 ${target.replace('chapter_', '')}`

const chapterNumber = (target: string): number | null => {
  const match = /^chapter_(\d+)$/.exec(target)
  return match ? Number(match[1]) : null
}

function markRunningAsError(stages: Record<StageKey, StageStatus>): Record<StageKey, StageStatus> {
  const next = { ...stages }
  for (const key of STAGE_ORDER) {
    if (next[key] === 'process') next[key] = 'error'
  }
  return next
}

export default function TaskPage() {
  const [query, setQuery] = useState('')
  const [running, setRunning] = useState(false)
  const [hasStarted, setHasStarted] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [stages, setStages] = useState<Record<StageKey, StageStatus>>(INITIAL_STAGES)
  const [stageNotes, setStageNotes] = useState<Record<string, string[]>>({})
  const [retrievalSkipped, setRetrievalSkipped] = useState(false)
  const [retrievedCount, setRetrievedCount] = useState<number | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [outline, setOutline] = useState<string[]>([])
  const [chapterStatus, setChapterStatus] = useState<Record<number, 'written' | 'passed' | 'failed'>>({})
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
  const resultRef = useRef<HTMLDivElement | null>(null)

  // 运行中的本地计时（SSE 协议不含耗时字段，计时在前端完成）
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => {
      if (startedAtRef.current !== null) {
        setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000))
      }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [running])

  // 完成/失败后自动定位到结果（唯一动效）
  useEffect(() => {
    if (finalAnswer !== null) {
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [finalAnswer])

  const addNote = (stage: string, note: string) => {
    setStageNotes((prev) => ({ ...prev, [stage]: [...(prev[stage] ?? []), note] }))
  }

  const handleEvent = (event: TaskEvent) => {
    if (event.task_id) setTaskId(event.task_id)

    if (event.event === 'task_failed') {
      setStages((prev) => markRunningAsError(prev))
      setError(event.message)
      setDuration(Math.floor((Date.now() - (startedAtRef.current ?? Date.now())) / 1000))
      return
    }

    if (event.event === 'task_completed') {
      setStages({
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
        if (n !== null) setChapterStatus((prev) => ({ ...prev, [n]: 'failed' }))
      }
      setDuration(Math.floor((Date.now() - (startedAtRef.current ?? Date.now())) / 1000))
      setActiveTab('content')
      return
    }

    if (event.event === 'retrying') {
      // 校验未通过：稍后会重写章节或重新规划
      setStages((prev) => ({ ...prev, validator: 'wait' }))
      const target = event.target ?? ''
      const action = event.suggested_action
      const noteTarget: StageKey = action === 'replan' ? 'planner' : 'writer'
      addNote(noteTarget, event.message)
      if (event.exhausted) {
        const n = chapterNumber(target)
        if (n !== null) setChapterStatus((prev) => ({ ...prev, [n]: 'failed' }))
      }
      return
    }

    const match = /^(planner|researcher|outline|writer|validator|summarizer)_(started|completed)$/.exec(
      event.event,
    )
    if (!match) return
    const stage = match[1] as StageKey
    const phase = match[2]

    setStages((prev) => ({ ...prev, [stage]: phase === 'started' ? 'process' : 'finish' }))

    if (event.event === 'planner_completed') {
      setPlan(event.plan ?? null)
      if (event.plan && !event.plan.needs_retrieval) {
        setRetrievalSkipped(true)
        setStages((prev) => ({ ...prev, researcher: 'finish' }))
      }
    }
    if (event.event === 'researcher_completed') {
      setRetrievedCount(event.retrieved_count ?? 0)
    }
    if (event.event === 'outline_completed') {
      setOutline(event.outline ?? [])
      setChapterStatus({})
    }
    if (event.event === 'writer_completed') {
      const n = chapterNumber(event.step ?? '')
      if (n !== null) setChapterStatus((prev) => ({ ...prev, [n]: 'written' }))
    }
    if (event.event === 'validator_completed' && event.target?.startsWith('chapter_')) {
      const n = chapterNumber(event.target)
      if (n !== null) {
        setChapterStatus((prev) => ({ ...prev, [n]: event.passed ? 'passed' : 'written' }))
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
    setStages(INITIAL_STAGES)
    setStageNotes({})
    setRetrievalSkipped(false)
    setRetrievedCount(null)
    setPlan(null)
    setOutline([])
    setChapterStatus({})
    setValidation(null)
    setReplans(0)
    setSources([])
    setFinalAnswer(null)
    setCopied(false)
    setError(null)
    setElapsed(0)
    setDuration(null)
    setActiveTab('content')
  }

  const handleRun = async () => {
    const trimmed = query.trim()
    if (!trimmed || running) return

    setRunning(true)
    reset()
    setHasStarted(true)
    startedAtRef.current = Date.now()

    try {
      await streamTask(trimmed, handleEvent)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '任务执行失败，请稍后重试')
      setStages((prev) => markRunningAsError(prev))
      setDuration(Math.floor((Date.now() - (startedAtRef.current ?? Date.now())) / 1000))
    } finally {
      setRunning(false)
    }
  }

  const writtenCount = Object.values(chapterStatus).filter((s) => s !== 'failed').length
  const failedCount = Object.values(chapterStatus).filter((s) => s === 'failed').length

  const stageViews: StageView[] = STAGE_ORDER.map((key) => {
    const view: StageView = {
      key,
      title: STAGE_TITLES[key],
      status: stages[key],
      notes: stageNotes[key],
    }
    if (key === 'researcher') {
      view.skipped = retrievalSkipped
      if (!retrievalSkipped && retrievedCount !== null) {
        view.badge = <Tag color={retrievedCount > 0 ? 'blue' : 'orange'}>{retrievedCount} 条片段</Tag>
      }
    }
    if (key === 'writer' && outline.length > 0) {
      view.note = `已写 ${writtenCount}/${outline.length} 章`
      view.progress = { done: writtenCount, total: outline.length }
    }
    if (key === 'validator' && validation) {
      view.badge = (
        <Tag color={validation.passed ? 'green' : 'red'}>
          {validation.passed ? '通过' : '未通过'}
        </Tag>
      )
    }
    if (key === 'planner' && replans > 0) {
      view.badge = <Tag color="volcano">重新规划 {replans} 次</Tag>
    }
    return view
  })

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
              <Descriptions.Item label="大纲完成情况">
                共 {outline.length} 章
                {failedCount > 0 ? `，其中 ${failedCount} 章未通过` : '，全部通过校验'}
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
      key: 'outline',
      label: '大纲',
      children:
        outline.length > 0 ? (
          <ol className="plain-list">
            {outline.map((title, index) => {
              const status = chapterStatus[index + 1]
              return (
                <li key={`${index}-${title}`}>
                  <Tag
                    color={
                      status === 'passed' ? 'green' : status === 'failed' ? 'red' : 'default'
                    }
                  >
                    {status === 'passed' ? '通过' : status === 'failed' ? '未通过' : status === 'written' ? '已写' : '待写'}
                  </Tag>
                  {title}
                </li>
              )
            })}
          </ol>
        ) : (
          <Empty description="尚未生成大纲" />
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
              <Button type="primary" loading={running} onClick={() => void handleRun()}>
                运行任务
              </Button>
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
          stages={stageViews}
          elapsedSeconds={elapsed}
          running={running}
          hasStarted={hasStarted}
        />
      </Card>

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
