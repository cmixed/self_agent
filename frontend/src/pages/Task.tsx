import { Alert, Button, Card, Input, Space, Steps, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'

import MarkdownView from '../components/MarkdownView'
import { ApiError, getHealth, streamTask } from '../services/api'
import type { HealthResponse, Plan, Source, TaskEvent, Validation } from '../types/api'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const STAGE_ORDER = [
  'planner',
  'researcher',
  'outline',
  'writer',
  'validator',
  'summarizer',
] as const
type StageKey = (typeof STAGE_ORDER)[number]
type StageStatus = 'wait' | 'process' | 'finish' | 'error'

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

function markRunningAsError(stages: Record<StageKey, StageStatus>): Record<StageKey, StageStatus> {
  const next = { ...stages }
  for (const key of STAGE_ORDER) {
    if (next[key] === 'process') next[key] = 'error'
  }
  return next
}

const TARGET_LABEL = (target: string) =>
  target === 'document' ? '整篇文档' : `章节 ${target.replace('chapter_', '')}`

const chapterNumber = (target: string): number | null => {
  const match = /^chapter_(\d+)$/.exec(target)
  return match ? Number(match[1]) : null
}

export default function TaskPage() {
  const [query, setQuery] = useState('')
  const [running, setRunning] = useState(false)
  const [stages, setStages] = useState<Record<StageKey, StageStatus>>(INITIAL_STAGES)
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
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  const handleEvent = (event: TaskEvent) => {
    if (event.event === 'task_failed') {
      setStages((prev) => markRunningAsError(prev))
      setError(event.message)
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
      // 标记最终未通过校验的章节
      for (const target of event.result?.failed_chapters ?? []) {
        const n = chapterNumber(target)
        if (n !== null) setChapterStatus((prev) => ({ ...prev, [n]: 'failed' }))
      }
      return
    }
    if (event.event === 'retrying') {
      // 校验未通过，稍后会重新执行 writer / planner
      setStages((prev) => ({ ...prev, validator: 'wait' }))
      if (event.exhausted) {
        const n = chapterNumber(event.target ?? '')
        if (n !== null) setChapterStatus((prev) => ({ ...prev, [n]: 'failed' }))
      }
      return
    }

    const match =
      /^(planner|researcher|outline|writer|validator|summarizer)_(started|completed)$/.exec(
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
    setPlan(null)
    setOutline([])
    setChapterStatus({})
    setValidation(null)
    setReplans(0)
    setSources([])
    setFinalAnswer(null)
    setCopied(false)
    setError(null)
    setRetrievalSkipped(false)
    setRetrievedCount(null)
    setStages(INITIAL_STAGES)
  }

  const handleRun = async () => {
    const trimmed = query.trim()
    if (!trimmed || running) return

    setRunning(true)
    reset()

    try {
      await streamTask(trimmed, handleEvent)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '任务执行失败，请稍后重试')
      setStages((prev) => markRunningAsError(prev))
    } finally {
      setRunning(false)
    }
  }

  const finishedCount = STAGE_ORDER.filter((key) => stages[key] === 'finish').length
  const writtenCount = Object.values(chapterStatus).filter((s) => s !== 'failed').length
  const chapterHint =
    outline.length > 0 && stages.writer !== 'wait'
      ? `（已写 ${writtenCount}/${outline.length} 章）`
      : ''

  const stepItems = STAGE_ORDER.map((key) => ({
    title:
      key === 'researcher' && retrievalSkipped ? '未检索（计划不需要知识库）' : STAGE_TITLES[key],
    description: key === 'writer' ? chapterHint || undefined : undefined,
    status:
      stages[key] === 'finish'
        ? ('finish' as const)
        : stages[key] === 'process'
          ? ('process' as const)
          : stages[key] === 'error'
            ? ('error' as const)
            : ('wait' as const),
  }))

  return (
    <Space
      direction="vertical"
      size="middle"
      style={{ width: '100%', maxWidth: 900, margin: '0 auto' }}
    >
      <Space>
        <Text type="secondary">后端状态：</Text>
        {health ? (
          <Tag color={health.status === 'ok' ? 'green' : 'red'}>
            {health.status} · {health.llm_provider}
            {health.llm_configured ? '' : '（未配置 API Key）'}
          </Tag>
        ) : (
          <Tag color="default">无法连接后端</Tag>
        )}
      </Space>

      <Card title="提交任务">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <TextArea
            rows={3}
            value={query}
            placeholder="例如：根据我的资料写一篇 RAG 技术综述"
            onChange={(event) => setQuery(event.target.value)}
          />
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
        </Space>
      </Card>

      <Card title="执行进度">
        <Steps direction="vertical" size="small" current={finishedCount} items={stepItems} />
        <Space style={{ marginTop: 12 }}>
          {retrievedCount !== null && (
            <span>
              <Text type="secondary">知识库命中：</Text>
              <Tag color={retrievedCount > 0 ? 'blue' : 'orange'}>{retrievedCount} 条片段</Tag>
            </span>
          )}
          {replans > 0 && <Tag color="volcano">已重新规划 {replans} 次</Tag>}
        </Space>
      </Card>

      {error && <Alert type="error" showIcon message={error} />}

      {plan && (
        <Card title="研究计划">
          <Paragraph style={{ marginBottom: 8 }}>
            <Text strong>目标：</Text>
            {plan.goal}
          </Paragraph>
          <Paragraph style={{ marginBottom: 8 }}>
            <Text strong>是否需要知识库检索：</Text>
            <Tag color={plan.needs_retrieval ? 'blue' : 'default'}>
              {plan.needs_retrieval ? '需要' : '不需要'}
            </Tag>
          </Paragraph>
          <ol style={{ paddingLeft: 20, margin: 0 }}>
            {plan.steps.map((step) => (
              <li key={step.id} style={{ marginBottom: 6 }}>
                <Tag>{step.type}</Tag>
                {step.description}
              </li>
            ))}
          </ol>
        </Card>
      )}

      {outline.length > 0 && (
        <Card title="文章大纲">
          <ol style={{ paddingLeft: 20, margin: 0 }}>
            {outline.map((title, index) => {
              const num = index + 1
              const status = chapterStatus[num]
              return (
                <li key={`${index}-${title}`} style={{ marginBottom: 6 }}>
                  <Text type={status === undefined ? 'secondary' : undefined}>
                    {status === 'passed' ? '✓ ' : status === 'failed' ? '✗ ' : status === 'written' ? '• ' : '○ '}
                    {title}
                  </Text>
                  {status === 'failed' && (
                    <Tag color="red" style={{ marginLeft: 8 }}>
                      未通过校验
                    </Tag>
                  )}
                </li>
              )
            })}
          </ol>
        </Card>
      )}

      {validation && (
        <Card title="内容校验">
          <Paragraph style={{ marginBottom: 8 }}>
            <Text strong>校验对象：</Text>
            {TARGET_LABEL(validation.target)}
            <Tag style={{ marginLeft: 8 }} color={validation.passed ? 'green' : 'red'}>
              {validation.passed ? '通过' : '未通过'}
            </Tag>
          </Paragraph>
          {validation.issues.length > 0 && (
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              {validation.issues.map((issue, index) => (
                <li key={index} style={{ marginBottom: 4 }}>
                  <Text type="warning">{issue}</Text>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {sources.length > 0 && (
        <Card title="参考来源">
          <ol style={{ paddingLeft: 20, margin: 0 }}>
            {sources.map((source) => (
              <li key={source.chunk_id} style={{ marginBottom: 6 }}>
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
        </Card>
      )}

      {finalAnswer !== null && (
        <Card
          title="最终结果"
          extra={
            <Space>
              <Button size="small" onClick={() => void handleCopy()}>
                {copied ? '已复制' : '复制'}
              </Button>
              <Button size="small" onClick={handleDownload}>
                下载 .md
              </Button>
            </Space>
          }
        >
          <MarkdownView content={finalAnswer} />
        </Card>
      )}
    </Space>
  )
}
