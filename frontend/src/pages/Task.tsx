import {
  ApiOutlined,
  ArrowRightOutlined,
  BulbOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DatabaseOutlined,
  DownOutlined,
  DownloadOutlined,
  EditOutlined,
  FileTextOutlined,
  HistoryOutlined,
  InfoCircleOutlined,
  LoadingOutlined,
  MailOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  StopOutlined,
  ThunderboltOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Dropdown,
  Input,
  Result,
  Segmented,
  Skeleton,
  Space,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import type { MenuProps } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import AgentProgress from '../components/AgentProgress'
import type { MacroStage } from '../components/AgentProgress'
import EmptyState from '../components/EmptyState'
import MarkdownReader from '../components/MarkdownReader'
import PageContainer from '../components/PageContainer'
import PresetDetailModal from '../components/PresetDetailModal'
import ScopePicker from '../components/ScopePicker'
import Section from '../components/Section'
import SendEmailModal from '../components/SendEmailModal'
import SourceList from '../components/SourceList'
import StatStrip from '../components/StatStrip'
import StatusTag from '../components/StatusTag'
import { listCategories, listDocuments, listTasks } from '../services/api'
import { usePresets } from '../hooks/usePresets'
import { useNav } from '../state/nav'
import { useTaskRun } from '../state/taskRun'
import type {
  CategoryInfo,
  DocumentInfo,
  PresetInfo,
  RetrievalMode,
  TaskDepth,
  TaskScope,
  TaskSummary,
} from '../types/api'
import {
  cacheHitRate,
  formatDateTime,
  formatDuration,
  formatTokenRate,
  formatTokens,
} from '../utils/format'
import { pickLastTask, splitWorkspacePresets, WORKSPACE_PRESET_LIMIT } from '../utils/presets'
import { runningTaskStage } from '../utils/runningTasks'
import { describeScope } from '../utils/scope'
import { readTaskOptionsMemory, sanitizeScope, saveTaskOptions } from '../utils/taskOptions'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const EYEBROW = '工作台'
const IDLE_TITLE = '让 Agent 基于你的资料完成一个复杂任务'
const IDLE_DESC = 'Agent 会规划任务、检索你的知识库，再分章节撰写并进行自我校验。'

/** 执行阶段的图标（与真实拓扑的 6 个节点一一对应） */
const STAGE_ICONS: Record<string, ReactNode> = {
  answer: <ThunderboltOutlined />,
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

const MODE_LABEL: Record<string, string> = {
  direct: '直接回答',
  brief: '简洁回答',
  longform: '长文',
}

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
  const { message } = App.useApp()
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
    copied,
    run: startRun,
    abort,
    clear,
    copy,
    download,
    tasksVersion,
    selectTask,
    rerun,
  } = useTaskRun()

  const { presets, loaded: presetsLoaded } = usePresets()
  const resultRef = useRef<HTMLDivElement | null>(null)
  const [documents, setDocuments] = useState<DocumentInfo[] | null>(null)
  const [recentTasks, setRecentTasks] = useState<TaskSummary[]>([])
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [scope, setScope] = useState<TaskScope>({ category_ids: [], document_ids: [] })
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>('all')
  // 打开范围选择器前的模式：取消时恢复，避免误改「全部 / 不检索」
  const scopeModeBeforePickerRef = useRef<RetrievalMode>('all')
  const [scopePickerOpen, setScopePickerOpen] = useState(false)
  const [detailPreset, setDetailPreset] = useState<PresetInfo | null>(null)
  const [emailOpen, setEmailOpen] = useState(false)
  const [outputTab, setOutputTab] = useState('plan')
  // 「上次任务」固定占预设区第一个槽位，因此可见预设少一条
  const lastTask = useMemo(() => pickLastTask(recentTasks), [recentTasks])
  const { visible: workspacePresets, hidden: hiddenPresets } = useMemo(
    () =>
      splitWorkspacePresets(
        presets,
        lastTask ? WORKSPACE_PRESET_LIMIT - 1 : WORKSPACE_PRESET_LIMIT,
      ),
    [lastTask, presets],
  )
  // 执行选项记忆：开关在「设置」页，这里只负责套用与记录
  const [optionMemory] = useState(() => readTaskOptionsMemory())
  const optionsHydratedRef = useRef(false)

  // 闲置态：轻量读取资料与类别（环境感知；失败静默，不打扰主流程）
  useEffect(() => {
    if (hasStarted) return
    let cancelled = false
    Promise.all([listDocuments(), listCategories()])
      .then(([docs, categoryData]) => {
        if (cancelled) return
        setDocuments(docs.documents)
        setCategories(categoryData.categories)
      })
      .catch(() => {
        if (!cancelled) setDocuments([])
      })
    return () => {
      cancelled = true
    }
  }, [hasStarted])

  // 「记住执行选项」已开启时：资料列表就绪后恢复一次（含失效 id 清理）
  useEffect(() => {
    if (optionsHydratedRef.current || documents === null) return
    optionsHydratedRef.current = true
    if (!optionMemory.remember) return
    const remembered = optionMemory.options
    setDepth(remembered.depth)
    setUseSkills(remembered.useSkills)
    setRetrievalMode(remembered.retrievalMode)
    const hadScope = remembered.scope.category_ids.length + remembered.scope.document_ids.length > 0
    const { scope: restored, dropped } = sanitizeScope(remembered.scope, categories, documents)
    setScope(restored)
    if (dropped > 0) {
      const empty = restored.category_ids.length + restored.document_ids.length === 0
      if (hadScope && empty && remembered.retrievalMode === 'selected') {
        setRetrievalMode('all')
      }
      message.info(
        hadScope && empty
          ? '上次的检索范围已失效，已改为全部知识库'
          : `已忽略 ${dropped} 个不存在的检索范围项`,
      )
    }
  }, [categories, documents, message, optionMemory, setDepth, setUseSkills])

  // 开启记忆时随表单变化持久化；关闭时只在提交任务时记录「上一次实际使用」
  useEffect(() => {
    if (!optionMemory.remember || !optionsHydratedRef.current) return
    saveTaskOptions({ depth, useSkills, retrievalMode, scope })
  }, [depth, optionMemory.remember, retrievalMode, scope, useSkills])

  // 最近任务：任务状态变化（tasksVersion）时自动刷新，无需手动刷新页面
  useEffect(() => {
    if (hasStarted) return
    let cancelled = false
    listTasks(8)
      .then((tasks) => {
        // 保留 8 条：最近任务只展示 4 条，但「上次任务」需要跳过运行中的任务
        if (!cancelled) setRecentTasks(tasks.tasks)
      })
      .catch(() => {
        // 读取失败保持上一次结果
      })
    return () => {
      cancelled = true
    }
  }, [hasStarted, tasksVersion])

  // 结果出现后定位（含从其它页面切回来的情况）
  useEffect(() => {
    if (finalAnswer !== null) {
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [finalAnswer])

  const handleStart = () => {
    if (
      retrievalMode === 'selected' &&
      scope.category_ids.length + scope.document_ids.length === 0
    ) {
      message.warning('请先选择检索范围，或改用全部知识库 / 不检索')
      setScopePickerOpen(true)
      return
    }
    // 提交即视为「上一次实际使用」，关闭记忆时也为下次开启留档
    saveTaskOptions({ depth, useSkills, retrievalMode, scope })
    void startRun(undefined, scope, retrievalMode)
  }

  // 当前选择范围的可读描述（含涉及文档数）
  const scopeDescription = useMemo(
    () => describeScope(scope, categories, documents ?? []),
    [scope, categories, documents],
  )
  const scopeCount = scope.category_ids.length + scope.document_ids.length

  /** 预设绑定的范围（未绑定 / 两者皆空则返回 null，表示沿用工作台当前选择）。 */
  const presetScope = (preset: PresetInfo): TaskScope | null =>
    preset.scope && preset.scope.category_ids.length + preset.scope.document_ids.length > 0
      ? preset.scope
      : null

  /** 预设任务：填入输入框（同时套用其绑定范围），等用户确认后回车运行。 */
  const handlePresetFill = (preset: PresetInfo) => {
    setQuery(preset.query)
    const bound = presetScope(preset)
    if (bound) {
      setScope(bound)
      setRetrievalMode('selected')
    }
    document.getElementById('task-query')?.focus()
  }

  /** 预设任务：一键直接运行（会覆盖输入框内容与范围，与实际执行保持一致）。 */
  const handlePresetRun = (preset: PresetInfo) => {
    if (running) return
    const bound = presetScope(preset)
    setQuery(preset.query)
    if (bound) {
      // 绑定范围当前覆盖 0 篇文档：不发注定 409 的任务，先引导用户修正范围
      if (documents !== null && describeScope(bound, categories, documents).invalid) {
        setScope(bound)
        scopeModeBeforePickerRef.current = 'all'
        setRetrievalMode('selected')
        setScopePickerOpen(true)
        message.warning('该预设绑定的范围当前没有文档，请调整检索范围后再运行')
        return
      }
      setScope(bound)
    }
    if (
      !bound &&
      retrievalMode === 'selected' &&
      scope.category_ids.length + scope.document_ids.length === 0
    ) {
      setScopePickerOpen(true)
      message.warning('当前是「指定范围」但还没有选择资料，请先选择范围')
      return
    }
    const effectiveScope = bound ?? scope
    const effectiveMode: RetrievalMode = bound ? 'selected' : retrievalMode
    if (bound) setRetrievalMode('selected')
    saveTaskOptions({ depth, useSkills, retrievalMode: effectiveMode, scope: effectiveScope })
    void startRun(preset.query, effectiveScope, effectiveMode)
  }

  /** 点击预设卡片：只填入输入框（不执行），是否运行交给「直接运行」按钮 / 详情浮窗。 */
  const handlePresetOpen = (preset: PresetInfo) => {
    handlePresetFill(preset)
  }

  /** 详情浮窗里的动作：先关闭浮窗，再填入或运行。 */
  const handleDetailFill = (preset: PresetInfo) => {
    setDetailPreset(null)
    handlePresetFill(preset)
  }

  const handleDetailRun = (preset: PresetInfo) => {
    setDetailPreset(null)
    handlePresetRun(preset)
  }

  // 前 6 条之外的预设：点击填入，「直接运行」按钮立即执行，不能只留在管理页
  const hiddenPresetItems: MenuProps['items'] = hiddenPresets.map((preset) => ({
    key: preset.preset_id,
    label: (
      <div className="ws-preset-more">
        <div className="ws-preset-more__head">
          <span className="ws-preset-more__title">{preset.title}</span>
          <Button
            type="link"
            size="small"
            className="ws-preset-more__run"
            disabled={running}
            onClick={(event) => {
              event.stopPropagation()
              handlePresetRun(preset)
            }}
          >
            直接运行
          </Button>
        </div>
        <span className="ws-preset-more__desc">{preset.description}</span>
      </div>
    ),
  }))

  const handleHiddenPresetClick: MenuProps['onClick'] = ({ key }) => {
    const preset = hiddenPresets.find((item) => item.preset_id === key)
    if (preset) handlePresetOpen(preset)
  }

  /**
   * 新建任务：断开当前任务的观察（不取消后端任务），回到输入区。
   *
   * 旧任务会继续在后台执行并留在顶栏胶囊里，用户可以立即提交第二个任务。
   */
  const handleNewTask = () => {
    setQuery('')
    clear()
    setOutputTab('plan')
    // 等 idle 视图挂载后再聚焦输入框，减少一次点击
    window.setTimeout(() => document.getElementById('task-query')?.focus(), 0)
  }

  /** 「上次任务」：沿用原任务的 query / 范围 / 深度 / 技能重新执行（新 task_id）。 */
  const handleLastTaskRun = () => {
    if (!lastTask) return
    void rerun(lastTask.task_id, lastTask.query)
  }

  const handleRetrievalModeChange = (value: RetrievalMode) => {
    if (value === 'selected') {
      scopeModeBeforePickerRef.current = retrievalMode
      setRetrievalMode('selected')
      setScopePickerOpen(true)
      return
    }
    setRetrievalMode(value)
  }

  const openScopePicker = () => {
    scopeModeBeforePickerRef.current = retrievalMode
    setScopePickerOpen(true)
  }

  const handleScopeConfirm = (selection: TaskScope) => {
    setScope(selection)
    setScopePickerOpen(false)
    // 选择器里切到「全部知识库」时同步回 all，避免留下无效的 selected
    if (selection.category_ids.length + selection.document_ids.length === 0) {
      setRetrievalMode('all')
    }
  }

  const handleScopeCancel = () => {
    setScopePickerOpen(false)
    // 取消 = 放弃本次模式切换（例如从「全部 / 不检索」点进「指定范围」后又取消）
    setRetrievalMode(scopeModeBeforePickerRef.current)
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
  const isLight = mode === 'direct' || mode === 'brief'

  const macroStages: MacroStage[] = isLight
    ? [
        {
          key: 'answer',
          title:
            mode === 'direct'
              ? '生成直接回答'
              : profile?.needs_retrieval
                ? '检索并生成简洁回答'
                : '生成简洁回答',
          status: nodes.answer as MacroStage['status'],
          note: profile?.reason,
          badge: finalAnswer !== null ? <Tag color="green">已生成</Tag> : undefined,
        },
      ]
    : [
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
                badge:
                  skillSteps.length > 0 ? (
                    <Tag color="green">{skillSteps.length} 个</Tag>
                  ) : undefined,
                notes: skillNotes,
              },
            ]
          : []),
        {
          key: 'outline',
          title: '生成文章大纲',
          status: nodes.outline as MacroStage['status'],
          badge:
            outline.length > 0 ? (
              <Tag color={writingBudget?.source_limited ? 'orange' : undefined}>
                {outline.length} 章
              </Tag>
            ) : undefined,
          note: writingBudget?.source_limited
            ? `资料约 ${writingBudget.source_chars} 字，参考篇幅调整为 ${writingBudget.effective_chars} 字`
            : undefined,
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
  if (mode) metrics.push(`模式：${MODE_LABEL[mode] ?? mode}`)
  if (scopeLabel) metrics.push(`范围：${scopeLabel}`)
  if (outline.length > 0) metrics.push(`${outline.length} 章`)
  if (writingBudget?.source_limited) {
    metrics.push(
      `资料约 ${writingBudget.source_chars} 字 → 参考 ${writingBudget.effective_chars} 字`,
    )
  }
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
  if (activeStage?.key === 'answer') {
    if (profile?.reason) currentFacts.push(profile.reason)
    if (profile?.needs_retrieval) currentFacts.push('会先检索个人知识库')
    if (profile?.estimated_calls) currentFacts.push(`预计 ${profile.estimated_calls} 次模型调用`)
  }
  if (activeStage?.key === 'planner' && plan?.goal) currentFacts.push(plan.goal)
  if (activeStage?.key === 'researcher' && retrievedCount !== null) {
    currentFacts.push(`命中 ${retrievedCount} 个文本块`)
  }
  if (activeStage?.key === 'outline' && outline.length > 0) {
    currentFacts.push(`共 ${outline.length} 章`)
  }
  if (activeStage?.key === 'outline' && writingBudget?.source_limited) {
    currentFacts.push(
      `资料约 ${writingBudget.source_chars} 字，按可支撑范围收束为 ${writingBudget.effective_chars} 字`,
    )
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
  const hitRate = cacheHitRate(usage)

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
                <Tag color={step.type === 'skill' ? 'green' : undefined}>
                  {STEP_TYPE_LABEL(step.type)}
                </Tag>
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
        <Section
          title="创建任务"
          description="描述一个需要多步完成的任务，Agent 会自动规划并执行"
        />

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
              <Text type="secondary">执行深度：</Text>
              <Segmented
                size="small"
                value={depth}
                disabled={running}
                onChange={(value) => setDepth(value as TaskDepth)}
                options={[
                  { label: '自动', value: 'auto' },
                  { label: '简洁', value: 'brief' },
                  { label: '长文', value: 'longform' },
                ]}
              />
              <Tooltip title="默认关闭；勾选后 Planner 才会看到技能目录，并可能增加模型调用">
                <Checkbox
                  checked={useSkills}
                  disabled={running || depth === 'brief'}
                  onChange={(event) => setUseSkills(event.target.checked)}
                >
                  允许技能
                </Checkbox>
              </Tooltip>
              <Tooltip title="在设置中管理默认值：记住上次的执行选项、检索范围与提醒">
                <Button
                  type="link"
                  size="small"
                  icon={<SettingOutlined />}
                  onClick={() => navigate('settings')}
                >
                  默认值
                </Button>
              </Tooltip>
            </Space>
          </div>

          <div className="ws-compose__scope">
            <Space size={8} wrap>
              <Text type="secondary">检索范围：</Text>
              <Segmented
                size="small"
                value={retrievalMode}
                disabled={running}
                onChange={(value) => handleRetrievalModeChange(value as RetrievalMode)}
                options={[
                  { label: '全部知识库', value: 'all' },
                  { label: '指定范围', value: 'selected' },
                  { label: '不检索', value: 'none' },
                ]}
              />
              {retrievalMode === 'selected' ? (
                <>
                  <Tag color={scopeCount === 0 ? 'orange' : 'green'}>{scopeDescription.label}</Tag>
                  <Button size="small" onClick={openScopePicker} disabled={running}>
                    编辑范围
                  </Button>
                </>
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
          description="点击卡片填入输入框；点卡片上的「直接运行」立即执行，点右上角「详情」查看完整任务与检索范围"
          extra={
            <Space size={4}>
              {hiddenPresets.length > 0 ? (
                <Dropdown
                  trigger={['click']}
                  menu={{ items: hiddenPresetItems, onClick: handleHiddenPresetClick }}
                >
                  <Button type="link" size="small">
                    更多（{hiddenPresets.length}） <DownOutlined />
                  </Button>
                </Dropdown>
              ) : null}
              <Button type="link" size="small" onClick={() => navigate('presets')}>
                管理预设 <ArrowRightOutlined />
              </Button>
            </Space>
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
        ) : presets.length === 0 && !lastTask ? (
          <EmptyState
            compact
            title="还没有预设任务"
            hint="到「预设任务」页新增，或在下方直接描述任务"
          />
        ) : (
          <div className="ws-presets">
            {lastTask ? (
              <Tooltip
                title={`${lastTask.query}（沿用原检索范围 / 深度 / 技能重新执行）`}
                placement="top"
              >
                <Card
                  size="small"
                  className="ws-preset ws-preset--last"
                  hoverable
                  onClick={handleLastTaskRun}
                >
                  <div className="ws-preset__body">
                    <div className="ws-preset__title ws-preset__title--last">
                      <span className="ws-preset__last-label">
                        <HistoryOutlined /> 上次任务
                      </span>
                      <StatusTag status={lastTask.status} />
                    </div>
                    <div className="ws-preset__desc">{lastTask.query}</div>
                  </div>
                  <div className="ws-preset__actions">
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      icon={<ReloadOutlined />}
                      onClick={(event) => {
                        event.stopPropagation()
                        handleLastTaskRun()
                      }}
                    >
                      再次运行
                    </Button>
                  </div>
                </Card>
              </Tooltip>
            ) : null}
            {workspacePresets.map((preset) => {
              const bound = presetScope(preset)
              const scopeInfo = bound ? describeScope(bound, categories, documents ?? []) : null
              return (
                <Card
                  key={preset.preset_id}
                  size="small"
                  className="ws-preset"
                  hoverable
                  onClick={() => handlePresetOpen(preset)}
                >
                  <div className="ws-preset__body">
                    <div className="ws-preset__title">
                      <span className="ws-preset__title-text">{preset.title}</span>
                      <Tooltip title="查看完整任务与检索范围">
                        <Button
                          type="text"
                          size="small"
                          className="ws-preset__detail"
                          icon={<InfoCircleOutlined />}
                          aria-label="预设详情"
                          onClick={(event) => {
                            event.stopPropagation()
                            setDetailPreset(preset)
                          }}
                        >
                          详情
                        </Button>
                      </Tooltip>
                    </div>
                    <div className="ws-preset__desc">{preset.description}</div>
                    {scopeInfo ? (
                      <Tag
                        className="ws-preset__scope"
                        color={scopeInfo.invalid ? 'orange' : 'default'}
                      >
                        范围：{scopeInfo.label}
                      </Tag>
                    ) : null}
                  </div>
                  <div className="ws-preset__actions">
                    <Space size={4}>
                      <Button
                        size="small"
                        onClick={(event) => {
                          event.stopPropagation()
                          handlePresetFill(preset)
                        }}
                      >
                        填入
                      </Button>
                      <Button
                        size="small"
                        type="primary"
                        ghost
                        disabled={running}
                        onClick={(event) => {
                          event.stopPropagation()
                          handlePresetRun(preset)
                        }}
                      >
                        直接运行
                      </Button>
                    </Space>
                  </div>
                </Card>
              )
            })}
          </div>
        )}

        <ScopePicker
          open={scopePickerOpen}
          initialMode={retrievalMode === 'selected' ? 'selected' : 'all'}
          categories={categories}
          documents={documents ?? []}
          value={scope}
          onCancel={handleScopeCancel}
          onConfirm={handleScopeConfirm}
        />

        <PresetDetailModal
          preset={detailPreset}
          categories={categories}
          documents={documents ?? []}
          running={running}
          onClose={() => setDetailPreset(null)}
          onFill={handleDetailFill}
          onRun={handleDetailRun}
        />

        <SendEmailModal
          open={emailOpen}
          taskId={taskId}
          title={plan?.goal || query}
          onClose={() => setEmailOpen(false)}
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
                {recentTasks.slice(0, 4).map((task) =>
                  task.status === 'running' ? (
                    <li key={task.task_id}>
                      <button
                        type="button"
                        className="ws-recent__open"
                        aria-label={`在工作台查看运行中的任务：${task.query}`}
                        onClick={() => void selectTask(task.task_id)}
                      >
                        <StatusTag status={task.status} />
                        <span className="ws-recent__query">{task.query}</span>
                        <span className="ws-recent__time">{runningTaskStage(task)}</span>
                      </button>
                    </li>
                  ) : (
                    <li key={task.task_id}>
                      <StatusTag status={task.status} />
                      <span className="ws-recent__query">{task.query}</span>
                      <span className="ws-recent__time">{formatDateTime(task.created_at)}</span>
                    </li>
                  ),
                )}
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
          ? 'Agent 正在分步执行；可新建并行任务或终止，切换页面任务会继续。'
          : '执行已结束，可在下方查看最终结果与来源。'
      }
    >
      <div className="ws-run__bar">
        <StatusTag status={statusKey} />
        {mode ? <Tag color={isLight ? 'cyan' : 'geekblue'}>{MODE_LABEL[mode] ?? mode}</Tag> : null}
        <span className="ws-run__meta">{metrics.join(' · ')}</span>
        <div className="ws-run__actions">
          <Tooltip
            title={
              running
                ? '当前任务转入后台继续执行，不会取消；可随时从顶栏胶囊切回'
                : '清空当前结果，开始一个新任务'
            }
          >
            <Button size="small" icon={<PlusOutlined />} onClick={handleNewTask}>
              新建任务
            </Button>
          </Tooltip>
          {running ? (
            <Button size="small" danger icon={<StopOutlined />} onClick={abort}>
              终止任务
            </Button>
          ) : null}
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
                <Tooltip title="把正文与 Markdown 附件发送到邮箱">
                  <Button
                    size="small"
                    icon={<MailOutlined />}
                    disabled={running || !taskId}
                    onClick={() => setEmailOpen(true)}
                  >
                    发送到邮箱
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
                  label: '参考篇幅',
                  value: writingBudget ? `${writingBudget.effective_chars} 字` : '—',
                  hint: writingBudget
                    ? `请求 ${writingBudget.requested_chars} 字 · 资料 ${writingBudget.source_chars} 字`
                    : undefined,
                },
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
                {
                  label: 'Token 消耗',
                  value: usage ? formatTokens(usage.total_tokens) : '—',
                  hint: usage
                    ? `入 ${formatTokens(usage.prompt_tokens)} · 出 ${formatTokens(usage.completion_tokens)}`
                    : undefined,
                },
                {
                  label: '缓存命中',
                  value: hitRate === null ? '—' : `${Math.round(hitRate * 100)}%`,
                  hint: usage
                    ? usage.cache_reported
                      ? `${formatTokens(usage.cache_hit_tokens)} tokens`
                      : '模型未上报'
                    : undefined,
                },
              ]}
            />
            {usage && usage.calls > 0 ? (
              <div className="result-usage">
                模型调用 {usage.calls} 次 · 模型耗时 {formatDuration(usage.llm_seconds)} ·{' '}
                {formatTokenRate(usage.tokens_per_second)}
                {usage.models.length > 0 ? ` · ${usage.models.join(' / ')}` : ''}
              </div>
            ) : null}
            <div className="result-body">
              <MarkdownReader content={finalAnswer} sources={sources} />
            </div>
          </Card>
        </div>
      ) : null}
    </PageContainer>
  )
}
