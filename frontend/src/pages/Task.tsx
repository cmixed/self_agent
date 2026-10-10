import {
  ApiOutlined,
  ArrowRightOutlined,
  BulbOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DatabaseOutlined,
  DownloadOutlined,
  EditOutlined,
  FileTextOutlined,
  LoadingOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
  ThunderboltOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Input,
  Result,
  Skeleton,
  Space,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import AgentProgress from '../components/AgentProgress'
import type { MacroStage } from '../components/AgentProgress'
import EmptyState from '../components/EmptyState'
import MarkdownReader from '../components/MarkdownReader'
import PageContainer from '../components/PageContainer'
import ScopePicker from '../components/ScopePicker'
import Section from '../components/Section'
import SourceList from '../components/SourceList'
import StatStrip from '../components/StatStrip'
import StatusTag from '../components/StatusTag'
import { listCategories, listDocuments, listTasks } from '../services/api'
import { usePresets } from '../hooks/usePresets'
import { useNav } from '../state/nav'
import { useTaskRun } from '../state/taskRun'
import type { CategoryInfo, DocumentInfo, TaskScope, TaskSummary } from '../types/api'
import { formatDateTime, formatDuration } from '../utils/format'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const EYEBROW = '工作台'
const IDLE_TITLE = '让 Agent 基于你的资料完成一个复杂任务'
const IDLE_DESC = 'Agent 会规划任务、检索你的知识库，再分章节撰写并进行自我校验。'

/** 执行阶段的图标（与真实拓扑的 6 个节点一一对应） */
const STAGE_ICONS: Record<string, ReactNode> = {
  planner: <BulbOutlined />,
  researcher: <DatabaseOutlined />,
  skills: <ApiOutlined />,
  outline: <UnorderedListOutlined />,
  writer: <EditOutlined />,
  validator: <SafetyCertificateOutlined />,
  summarizer: <FileTextOutlined />,
}

/** 闲置态展示的执行流程（未开始=tertiary） */
const PIPELINE_STEPS = [
  { key: 'planner', label: '规划任务' },
  { key: 'researcher', label: '检索知识库' },
  { key: 'outline', label: '生成大纲' },
  { key: 'writer', label: '逐章撰写' },
  { key: 'validator', label: '校验质量' },
  { key: 'summarizer', label: '整合结果' },
]

const TARGET_LABEL = (target: string) =>
  target === 'document' ? '整篇文档' : `章节 ${target.replace('chapter_', '')}`

/** 计划步骤类型 -> 中文标签（skill 为技能调用） */
const STEP_TYPE_LABEL = (type: string) =>
  (
    {
      retrieval: '检索',
      skill: '技能',
      outline: '大纲',
      writing: '撰写',
      validation: '校验',
    } as Record<string, string>
  )[type] ?? type

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
    skillNotes,
    scopeLabel,
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

  const { presets, loaded: presetsLoaded } = usePresets()
  const resultRef = useRef<HTMLDivElement | null>(null)
  const [documents, setDocuments] = useState<DocumentInfo[] | null>(null)
  const [recentTasks, setRecentTasks] = useState<TaskSummary[]>([])
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [scope, setScope] = useState<TaskScope>({ category_ids: [], document_ids: [] })
  const [scopePickerOpen, setScopePickerOpen] = useState(false)
  const [outputTab, setOutputTab] = useState('plan')

  // 闲置态：轻量读取资料与最近任务（环境感知；失败静默，不打扰主流程）
  useEffect(() => {
    if (hasStarted) return
    let cancelled = false
    Promise.all([listDocuments(), listTasks(), listCategories()])
      .then(([docs, tasks, categoryData]) => {
        if (cancelled) return
        setDocuments(docs.documents)
        setRecentTasks(tasks.tasks.slice(0, 4))
        setCategories(categoryData.categories)
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
    void startRun(undefined, scope)
  }

  const scopeCount = scope.category_ids.length + scope.document_ids.length
  const scopeSummary =
    scopeCount === 0
      ? '全部知识库'
      : `${scope.category_ids.length} 个类别 + ${scope.document_ids.length} 篇文档`

  /** 预设任务：点击卡片 = 填充输入框并聚焦（用户确认后再运行）。 */
  const handlePresetFill = (presetQuery: string) => {
    setQuery(presetQuery)
    document.getElementById('task-query')?.focus()
  }

  /** 预设任务：一键直接运行（会覆盖输入框内容，与实际执行保持一致）。 */
  const handlePresetRun = (presetQuery: string) => {
    if (running) return
    setQuery(presetQuery)
    void startRun(presetQuery, scope)
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

  const skillSteps = (plan?.steps ?? []).filter((step) => step.type === 'skill')
  const hasSkillStage = skillSteps.length > 0 || nodes.skills !== 'wait'

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
    ...(hasSkillStage
      ? [
          {
            key: 'skills',
            title: '应用技能',
            status: nodes.skills as MacroStage['status'],
            badge: skillSteps.length > 0 ? <Tag color="green">{skillSteps.length} 个</Tag> : undefined,
            notes: skillNotes,
          },
        ]
      : []),
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
  if (scopeLabel) metrics.push(`范围：${scopeLabel}`)
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

  // --- 当前步骤：全部来自真实运行状态，不涉及模型推理过程 ---
  const activeStage = macroStages.find((stage) => stage.status === 'process')
  const lastLog = log.length > 0 ? log[log.length - 1] : null

  const currentFacts: string[] = []
  if (activeStage?.key === 'planner' && plan?.goal) currentFacts.push(plan.goal)
  if (activeStage?.key === 'researcher' && retrievedCount !== null) {
    currentFacts.push(`命中 ${retrievedCount} 个文本块`)
  }
  if (activeStage?.key === 'outline' && outline.length > 0) {
    currentFacts.push(`共 ${outline.length} 章`)
  }
  if (activeStage?.key === 'writer' && outline.length > 0) {
    currentFacts.push(`已写 ${writtenChapters}/${outline.length} 章`)
    const writing = chapterList.find((chapter) => chapter.writing)
    if (writing) currentFacts.push(`正在生成第 ${writing.index} 章`)
  }
  if (activeStage?.key === 'validator') {
    currentFacts.push(
      `通过 ${passedCount} 章${failedCount > 0 ? ` · 未通过 ${failedCount} 章` : ''}`,
    )
  }

  const currentTitle =
    activeStage?.title ??
    (error ? '执行失败' : aborted ? '已终止' : finalAnswer !== null ? '已完成' : '准备中')
  const currentMessage =
    lastLog?.message ?? (activeStage ? `${activeStage.title}…` : running ? '正在启动…' : '')
  const currentIcon = error ? (
    <CloseCircleOutlined />
  ) : activeStage ? (
    STAGE_ICONS[activeStage.key]
  ) : finalAnswer !== null ? (
    <CheckCircleOutlined />
  ) : (
    <StopOutlined />
  )

  // --- 检索到的资料：按文档聚合（真实来源，按 chunk 去重计数） ---
  const sourceDocs = (() => {
    const grouped = new Map<string, { document_id: string; filename: string; chunks: number }>()
    for (const source of sources) {
      const existing = grouped.get(source.document_id)
      if (existing) existing.chunks += 1
      else
        grouped.set(source.document_id, {
          document_id: source.document_id,
          filename: source.filename,
          chunks: 1,
        })
    }
    return Array.from(grouped.values())
  })()

  const citationCount = finalAnswer ? (finalAnswer.match(/\[\d+\]/g)?.length ?? 0) : 0

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
                <Tag color={step.type === 'skill' ? 'green' : undefined}>{STEP_TYPE_LABEL(step.type)}</Tag>
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
  ]

  if (!hasStarted) {
    return (
      <PageContainer eyebrow={EYEBROW} title={IDLE_TITLE} description={IDLE_DESC}>
        <Section title="创建任务" description="描述一个需要多步完成的任务，Agent 会自动规划并执行" />

        <div className="ws-compose">
          <TextArea
            id="task-query"
            name="query"
            className="ws-compose__input"
            autoSize={{ minRows: 4, maxRows: 10 }}
            value={query}
            placeholder="描述需要多步完成的任务，或从下方预设任务中选择"
            onChange={(event) => setQuery(event.target.value)}
            onPressEnter={(event) => {
              // Enter 直接运行任务；Shift+Enter 换行
              if (!event.shiftKey && query.trim()) {
                event.preventDefault()
                handleStart()
              }
            }}
          />

          <div className="ws-compose__scope">
            <Space size={8} wrap>
              <Text type="secondary">检索范围：</Text>
              <Tag color={scopeCount === 0 ? 'default' : 'green'}>{scopeSummary}</Tag>
              <Button size="small" onClick={() => setScopePickerOpen(true)} disabled={running}>
                选择范围
              </Button>
              {scopeCount > 0 ? (
                <Button
                  size="small"
                  type="text"
                  icon={<CloseCircleOutlined />}
                  disabled={running}
                  onClick={() => setScope({ category_ids: [], document_ids: [] })}
                >
                  改为全部
                </Button>
              ) : null}
            </Space>
          </div>

          <div className="ws-compose__actions">
            <Text type="secondary" className="ws-compose__hint">
              Enter 运行任务 · Shift + Enter 换行 · 或从下方预设任务开始
            </Text>
            <Space>
              <Button disabled={!query.trim()} onClick={() => setQuery('')}>
                清空
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

        <Section
          title="预设任务"
          description="点击卡片填入输入框，也可一键直接运行"
          extra={
            <Button type="link" size="small" onClick={() => navigate('presets')}>
              查看全部 / 管理 <ArrowRightOutlined />
            </Button>
          }
        />

        {!presetsLoaded ? (
          <div className="ws-presets" aria-hidden="true">
            {[0, 1, 2].map((index) => (
              <Card key={index} size="small" className="ws-preset ws-preset--skeleton">
                <Skeleton active title={false} paragraph={{ rows: 2 }} />
              </Card>
            ))}
          </div>
        ) : presets.length === 0 ? (
          <EmptyState
            compact
            title="还没有预设任务"
            hint="到「预设任务」页新增，或在下方直接描述任务"
          />
        ) : (
          <div className="ws-presets">
            {presets.slice(0, 3).map((preset) => (
              <Tooltip key={preset.preset_id} title={preset.query} placement="top">
                <Card
                  size="small"
                  className="ws-preset"
                  hoverable
                  onClick={() => handlePresetFill(preset.query)}
                >
                  <div className="ws-preset__body">
                    <div className="ws-preset__title">{preset.title}</div>
                    <div className="ws-preset__desc">{preset.description}</div>
                  </div>
                  <div className="ws-preset__actions">
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      disabled={running}
                      onClick={(event) => {
                        event.stopPropagation()
                        handlePresetRun(preset.query)
                      }}
                    >
                      直接运行
                    </Button>
                  </div>
                </Card>
              </Tooltip>
            ))}
          </div>
        )}

        <ScopePicker
          open={scopePickerOpen}
          categories={categories}
          documents={documents ?? []}
          value={scope}
          onCancel={() => setScopePickerOpen(false)}
          onConfirm={(selection) => {
            setScope(selection)
            setScopePickerOpen(false)
          }}
        />

        <Section title="Agent 执行流程" description="运行时会按此顺序推进，并实时反馈当前阶段" />

        <div className="ws-pipeline">
          <div className="ws-pipeline__flow">
            {PIPELINE_STEPS.map((step, index) => (
              <span className="ws-pipeline__item" key={step.key}>
                {index > 0 ? <ArrowRightOutlined className="ws-pipeline__arrow" /> : null}
                <span className="ws-pipeline__step">
                  <span className="ws-pipeline__icon">{STAGE_ICONS[step.key]}</span>
                  {step.label}
                </span>
              </span>
            ))}
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
            title="执行阶段"
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
          <Card title="当前步骤" extra={running ? <Text type="secondary">进行中</Text> : null}>
            <div className={`current-step${activeStage && running ? ' is-active' : ''}`}>
              <span className="current-step__icon">{currentIcon}</span>
              <div className="current-step__body">
                <div className="current-step__title">
                  {currentTitle}
                  {activeStage && running ? (
                    <LoadingOutlined className="current-step__spin" />
                  ) : null}
                </div>
                {currentMessage ? <p className="current-step__message">{currentMessage}</p> : null}
                {currentFacts.length > 0 ? (
                  <ul className="current-step__facts">
                    {currentFacts.map((fact) => (
                      <li key={fact}>{fact}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </div>
          </Card>

          {sourceDocs.length > 0 ? (
            <Card title={`检索到的资料（${sourceDocs.length}）`}>
              <SourceList docs={sourceDocs} />
            </Card>
          ) : null}

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
            title="生成结果"
            extra={
              <Space>
                <Tooltip title="复制 Markdown 原文">
                  <Button size="small" onClick={() => void copy()}>
                    {copied ? '已复制' : '复制'}
                  </Button>
                </Tooltip>
                <Tooltip title="下载 Markdown 文件到本地">
                  <Button size="small" icon={<DownloadOutlined />} onClick={download}>
                    下载
                  </Button>
                </Tooltip>
                <Tooltip title="打印 / 导出 PDF">
                  <Button size="small" onClick={() => window.print()}>
                    打印
                  </Button>
                </Tooltip>
                <Tooltip title="用同一任务重新生成">
                  <Button
                    size="small"
                    icon={<ReloadOutlined />}
                    disabled={running}
                    onClick={handleStart}
                  >
                    重新生成
                  </Button>
                </Tooltip>
              </Space>
            }
          >
            <StatStrip
              items={[
                { label: '来源文档', value: sourceDocs.length },
                { label: '正文引用', value: citationCount },
                { label: '检索文本块', value: retrievedCount ?? 0 },
                {
                  label: '质量校验',
                  value: validation ? (
                    <span className={validation.passed ? 'ws-tone-ok' : 'ws-tone-bad'}>
                      {validation.passed ? '通过' : '未通过'}
                    </span>
                  ) : (
                    '—'
                  ),
                },
              ]}
            />
            <div className="result-body">
              <MarkdownReader content={finalAnswer} sources={sources} />
            </div>
          </Card>
        </div>
      ) : null}
    </PageContainer>
  )
}
