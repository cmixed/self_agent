import {
  ArrowRightOutlined,
  DownloadOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Alert, Button, Card, Input, Result, Space, Tabs, Tag, Tooltip, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'

import AgentProgress from '../components/AgentProgress'
import type { MacroStage } from '../components/AgentProgress'
import EmptyState from '../components/EmptyState'
import MarkdownReader from '../components/MarkdownReader'
import PageContainer from '../components/PageContainer'
import StatStrip from '../components/StatStrip'
import StatusTag from '../components/StatusTag'
import { listDocuments, listTasks } from '../services/api'
import { useNav } from '../state/nav'
import { SAMPLE_TASKS, useTaskRun } from '../state/taskRun'
import type { DocumentInfo, TaskSummary } from '../types/api'
import { formatDateTime, formatDuration } from '../utils/format'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const EYEBROW = '工作台'
const IDLE_TITLE = '让 Agent 基于你的资料完成一个复杂任务'
const IDLE_DESC = 'Agent 会先规划任务、检索你的知识库，再分章节撰写并逐章自我校验。'

const TARGET_LABEL = (target: string) =>
  target === 'document' ? '整篇文档' : `章节 ${target.replace('chapter_', '')}`

export default function TaskPage() {
  const { navigate } = useNav()
  const {
    query,
    setQuery,
    running,
    hasStarted,
    aborted,
    error,
    dismissError,
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
    copied,
    run: startRun,
    abort,
    clear,
    copy,
    download,
  } = useTaskRun()

  const resultRef = useRef<HTMLDivElement | null>(null)
  const [documents, setDocuments] = useState<DocumentInfo[] | null>(null)
  const [recentTasks, setRecentTasks] = useState<TaskSummary[]>([])
  const [outputTab, setOutputTab] = useState('plan')

  // 闲置态：轻量读取资料与最近任务（环境感知；失败静默，不打扰主流程）
  useEffect(() => {
    if (hasStarted) return
    let cancelled = false
    Promise.all([listDocuments(), listTasks()])
      .then(([docs, tasks]) => {
        if (cancelled) return
        setDocuments(docs.documents)
        setRecentTasks(tasks.tasks.slice(0, 4))
      })
      .catch(() => {
        if (!cancelled) setDocuments([])
      })
    return () => {
      cancelled = true
    }
  }, [hasStarted])

  // 结果出现后定位（含从其它页面切回来的情况）
  useEffect(() => {
    if (finalAnswer !== null) {
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [finalAnswer])

  const handleStart = () => {
    void startRun()
  }

  const handleReset = () => {
    setQuery('')
    clear()
    setOutputTab('plan')
  }

  // --- 执行主线：与真实拓扑一一对应（撰写 ⇄ 校验为独立节点，重试/重规划以小注回环呈现） ---
  const validatorBadge =
    passedCount > 0 || failedCount > 0 ? (
      <Space size={4}>
        {passedCount > 0 ? <Tag color="green">通过 {passedCount}</Tag> : null}
        {failedCount > 0 ? <Tag color="red">未通过 {failedCount}</Tag> : null}
      </Space>
    ) : undefined

  const validatorNotes = Object.entries(chapterNotes).flatMap(([chapter, notes]) =>
    notes.map((note) => `第 ${chapter} 章：${note}`),
  )

  const macroStages: MacroStage[] = [
    {
      key: 'planner',
      title: '分析任务',
      status: nodes.planner as MacroStage['status'],
      badge: replans > 0 ? <Tag color="volcano">重新规划 {replans} 次</Tag> : undefined,
      notes: plannerNotes,
    },
    {
      key: 'researcher',
      title: '检索知识库',
      status: nodes.researcher as MacroStage['status'],
      skipped: retrievalSkipped,
      badge:
        retrievedCount !== null ? (
          <Tag color={retrievedCount > 0 ? 'blue' : 'orange'}>{retrievedCount} 条片段</Tag>
        ) : undefined,
    },
    {
      key: 'outline',
      title: '生成文章大纲',
      status: nodes.outline as MacroStage['status'],
      badge: outline.length > 0 ? <Tag>{outline.length} 章</Tag> : undefined,
    },
    {
      key: 'writer',
      title: '逐章撰写',
      status: nodes.writer as MacroStage['status'],
      note: outline.length > 0 ? `已写 ${writtenChapters}/${outline.length} 章` : undefined,
      progress:
        outline.length > 0 ? { done: writtenChapters, total: outline.length } : undefined,
      chapters: chapterList,
    },
    {
      key: 'validator',
      title: '校验与重试',
      status: nodes.validator as MacroStage['status'],
      badge: validatorBadge,
      notes: validatorNotes,
    },
    {
      key: 'summarizer',
      title: '整合结果',
      status: nodes.summarizer as MacroStage['status'],
      badge: finalAnswer !== null ? <Tag color="green">已整合</Tag> : undefined,
    },
  ]

  const metrics: string[] = []
  if (outline.length > 0) metrics.push(`${outline.length} 章`)
  if (retrievedCount !== null) metrics.push(`命中 ${retrievedCount} 条`)
  if (replans > 0) metrics.push(`重新规划 ${replans} 次`)
  metrics.push(`用时 ${formatDuration(duration ?? elapsed)}`)

  const statusKey = running
    ? 'running'
    : error
      ? 'failed'
      : aborted
        ? 'cancelled'
        : finalAnswer !== null
          ? 'completed'
          : 'running'

  const outputTabs = [
    {
      key: 'plan',
      label: '计划',
      children: plan ? (
        <div className="ws-out">
          <Paragraph className="ws-out__goal">
            <Text strong>目标：</Text>
            {plan.goal}
          </Paragraph>
          <div className="ws-out__row">
            <Text strong>需要检索：</Text>
            <Tag color={plan.needs_retrieval ? 'blue' : 'default'}>
              {plan.needs_retrieval ? '是' : '否'}
            </Tag>
          </div>
          <ol className="plain-list">
            {plan.steps.map((step) => (
              <li key={step.id}>
                <Tag>{step.type}</Tag>
                {step.description}
              </li>
            ))}
          </ol>
        </div>
      ) : (
        <EmptyState compact title="尚未生成计划" />
      ),
    },
    {
      key: 'outline',
      label: '大纲',
      children:
        outline.length > 0 ? (
          <ol className="plain-list">
            {outline.map((title, index) => (
              <li key={index}>{title}</li>
            ))}
          </ol>
        ) : (
          <EmptyState compact title="尚未生成大纲" />
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
          <EmptyState compact title="尚未生成章节" />
        ),
    },
    {
      key: 'validation',
      label: '校验',
      children: validation ? (
        <div className="ws-out">
          <div className="ws-out__row">
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
        </div>
      ) : (
        <EmptyState compact title="尚未执行校验" />
      ),
    },
    {
      key: 'sources',
      label: '来源',
      children:
        sources.length > 0 ? (
          <ol className="plain-list">
            {sources.map((source) => (
              <li key={source.chunk_id}>
                <Text>
                  [{source.index}] {source.filename}
                  {source.page ? `（第 ${source.page} 页）` : ''}
                </Text>
                {typeof source.score === 'number' ? (
                  <Tag className="ws-source__score">相似度 {source.score.toFixed(3)}</Tag>
                ) : null}
              </li>
            ))}
          </ol>
        ) : (
          <EmptyState
            compact
            title="本次任务未使用知识库来源"
            hint="计划不需要检索，或知识库为空"
          />
        ),
    },
  ]

  if (!hasStarted) {
    return (
      <PageContainer eyebrow={EYEBROW} title={IDLE_TITLE} description={IDLE_DESC}>
        <div className="ws-compose">
          <TextArea
            id="task-query"
            name="query"
            autoSize={{ minRows: 4, maxRows: 10 }}
            value={query}
            placeholder="例如：根据我的资料写一篇 RAG 技术综述"
            onChange={(event) => setQuery(event.target.value)}
            onPressEnter={(event) => {
              // Enter 直接运行任务；Shift+Enter 换行
              if (!event.shiftKey && query.trim()) {
                event.preventDefault()
                handleStart()
              }
            }}
          />

          <div className="ws-compose__samples">
            <Text type="secondary">示例</Text>
            <Space size={[8, 8]} wrap>
              {SAMPLE_TASKS.map((sample) => (
                <Button key={sample} size="small" className="sample-chip" onClick={() => setQuery(sample)}>
                  {sample}
                </Button>
              ))}
            </Space>
          </div>

          <div className="ws-compose__actions">
            <Text type="secondary" className="ws-compose__hint">
              Enter 运行任务 · Shift + Enter 换行
            </Text>
            <Space>
              <Button disabled={!query.trim()} onClick={() => setQuery('')}>
                重置
              </Button>
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                disabled={!query.trim()}
                onClick={handleStart}
              >
                运行任务
              </Button>
            </Space>
          </div>
        </div>

        <div className="ws-idle-grid">
          <Card
            size="small"
            title="你的资料"
            extra={
              <Button size="small" type="link" onClick={() => navigate('knowledge')}>
                知识库 <ArrowRightOutlined />
              </Button>
            }
          >
            {documents === null ? (
              <Text type="secondary">读取中…</Text>
            ) : documents.length === 0 ? (
              <EmptyState compact title="还没有资料" hint="先去知识库上传 PDF / TXT / Markdown" />
            ) : (
              <StatStrip
                items={[
                  { label: '文档', value: documents.length },
                  {
                    label: '文本块',
                    value: documents.reduce((total, doc) => total + doc.chunks, 0),
                  },
                ]}
              />
            )}
          </Card>

          <Card
            size="small"
            title="最近任务"
            extra={
              <Button size="small" type="link" onClick={() => navigate('history')}>
                全部 <ArrowRightOutlined />
              </Button>
            }
          >
            {recentTasks.length === 0 ? (
              <EmptyState compact title="还没有任务记录" />
            ) : (
              <ul className="ws-recent">
                {recentTasks.map((task) => (
                  <li key={task.task_id}>
                    <StatusTag status={task.status} />
                    <span className="ws-recent__query">{task.query}</span>
                    <span className="ws-recent__time">{formatDateTime(task.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </PageContainer>
    )
  }

  return (
    <PageContainer
      eyebrow={EYEBROW}
      title={plan?.goal || query || '任务执行'}
      description={
        running
          ? 'Agent 正在分步执行，可随时终止；切换到其它页面任务会继续。'
          : '执行已结束，可在下方查看最终结果与来源。'
      }
    >
      <div className="ws-run__bar">
        <StatusTag status={statusKey} />
        <span className="ws-run__meta">{metrics.join(' · ')}</span>
        <div className="ws-run__actions">
          {running ? (
            <Button size="small" danger icon={<StopOutlined />} onClick={abort}>
              终止任务
            </Button>
          ) : (
            <Button size="small" onClick={handleReset}>
              新建任务
            </Button>
          )}
        </div>
      </div>

      <div className="ws-grid">
        <div className="ws-grid__main">
          <Card
            title="执行主线"
            extra={
              taskId ? (
                <Text type="secondary" copyable={{ text: taskId }}>
                  {taskId.slice(0, 8)}
                </Text>
              ) : null
            }
          >
            <AgentProgress
              stages={macroStages}
              elapsedSeconds={elapsed}
              running={running}
              hasStarted={hasStarted}
              round={round}
              log={log}
            />
          </Card>
        </div>

        <div className="ws-grid__side">
          <Card title="产出" extra={<Text type="secondary">{running ? '实时' : '已完成'}</Text>}>
            <Tabs size="small" activeKey={outputTab} onChange={setOutputTab} items={outputTabs} />
          </Card>
        </div>
      </div>

      {aborted ? (
        <Alert
          type="warning"
          showIcon
          title="任务已终止"
          description="已关闭与后端的连接，Agent 会同步取消，不会继续消耗模型调用。已生成的计划 / 大纲 / 章节进度保留在上方。"
        />
      ) : null}

      {error ? (
        <Result
          status="error"
          title="任务未能完成"
          subTitle={error}
          extra={
            <>
              <Button type="primary" onClick={handleStart} disabled={running}>
                重试
              </Button>
              <Button onClick={dismissError}>关闭</Button>
            </>
          }
        />
      ) : null}

      {finalAnswer !== null ? (
        <div ref={resultRef}>
          <Card
            title="最终结果"
            extra={
              <Space>
                <Tooltip title="复制 Markdown 原文">
                  <Button size="small" onClick={() => void copy()}>
                    {copied ? '已复制' : '复制'}
                  </Button>
                </Tooltip>
                <Tooltip title="下载 Markdown 文件到本地">
                  <Button size="small" icon={<DownloadOutlined />} onClick={download}>
                    下载 .md
                  </Button>
                </Tooltip>
                <Tooltip title="打印 / 导出 PDF">
                  <Button size="small" onClick={() => window.print()}>
                    打印
                  </Button>
                </Tooltip>
              </Space>
            }
          >
            <MarkdownReader content={finalAnswer} sources={sources} />
          </Card>
        </div>
      ) : null}
    </PageContainer>
  )
}
