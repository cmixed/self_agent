import { Alert, Button, Card, Input, Space, Steps, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { ApiError, getHealth, streamTask } from '../services/api'
import type { HealthResponse, Plan, Source, TaskEvent } from '../types/api'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const STAGE_ORDER = ['planner', 'researcher', 'writer', 'summarizer'] as const
type StageKey = (typeof STAGE_ORDER)[number]
type StageStatus = 'wait' | 'process' | 'finish' | 'error'

const STAGE_TITLES: Record<StageKey, string> = {
  planner: '分析任务并生成计划',
  researcher: '检索个人知识库',
  writer: '撰写内容',
  summarizer: '整合最终结果',
}

const INITIAL_STAGES: Record<StageKey, StageStatus> = {
  planner: 'wait',
  researcher: 'wait',
  writer: 'wait',
  summarizer: 'wait',
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
  const [stages, setStages] = useState<Record<StageKey, StageStatus>>(INITIAL_STAGES)
  const [retrievalSkipped, setRetrievalSkipped] = useState(false)
  const [retrievedCount, setRetrievedCount] = useState<number | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [finalAnswer, setFinalAnswer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)

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
      setStages({ planner: 'finish', researcher: 'finish', writer: 'finish', summarizer: 'finish' })
      setFinalAnswer(event.result?.final_answer ?? '')
      setSources(event.result?.sources ?? [])
      return
    }

    const match = /^(planner|researcher|writer|summarizer)_(started|completed)$/.exec(event.event)
    if (!match) return
    const stage = match[1] as StageKey
    const phase = match[2]

    setStages((prev) => ({ ...prev, [stage]: phase === 'started' ? 'process' : 'finish' }))

    if (event.event === 'planner_completed') {
      setPlan(event.plan ?? null)
      // 计划不需要检索时，researcher 阶段直接标记为跳过
      if (event.plan && !event.plan.needs_retrieval) {
        setRetrievalSkipped(true)
        setStages((prev) => ({ ...prev, researcher: 'finish' }))
      }
    }
    if (event.event === 'researcher_completed') {
      setRetrievedCount(event.retrieved_count ?? 0)
    }
  }

  const handleRun = async () => {
    const trimmed = query.trim()
    if (!trimmed || running) return

    setRunning(true)
    setError(null)
    setPlan(null)
    setSources([])
    setFinalAnswer(null)
    setRetrievalSkipped(false)
    setRetrievedCount(null)
    setStages(INITIAL_STAGES)

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
  const stepItems = STAGE_ORDER.map((key) => ({
    title:
      key === 'researcher' && retrievalSkipped ? '未检索（计划不需要知识库）' : STAGE_TITLES[key],
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
                setPlan(null)
                setSources([])
                setFinalAnswer(null)
                setError(null)
                setRetrievalSkipped(false)
                setRetrievedCount(null)
                setStages(INITIAL_STAGES)
              }}
            >
              清空
            </Button>
          </Space>
        </Space>
      </Card>

      <Card title="执行进度">
        <Steps direction="vertical" size="small" current={finishedCount} items={stepItems} />
        {retrievedCount !== null && (
          <Paragraph style={{ margin: '12px 0 0' }}>
            <Text type="secondary">知识库命中：</Text>
            <Tag color={retrievedCount > 0 ? 'blue' : 'orange'}>{retrievedCount} 条片段</Tag>
          </Paragraph>
        )}
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
        <Card title="最终结果">
          <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{finalAnswer}</Paragraph>
        </Card>
      )}
    </Space>
  )
}
