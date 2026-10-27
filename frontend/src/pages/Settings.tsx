import { ClearOutlined, DeleteOutlined, ReloadOutlined, SettingOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  InputNumber,
  Popconfirm,
  Segmented,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import PageContainer from '../components/PageContainer'
import { listCategories, listDocuments } from '../services/api'
import { useTaskRun } from '../state/taskRun'
import type { ThemeMode } from '../theme/config'
import type { CategoryInfo, DocumentInfo, TaskDepth } from '../types/api'
import { DEFAULT_PILL_SETTINGS, PILL_SETTING_RANGES } from '../utils/pillSettings'
import { describeScope } from '../utils/scope'
import {
  clearTaskOptionsMemory,
  defaultTaskOptionsMemory,
  readTaskOptionsMemory,
  sanitizeScope,
  setTaskOptionsRemember,
} from '../utils/taskOptions'
import type { TaskOptionsMemory } from '../utils/taskOptions'

const { Text } = Typography

const PAGE_MAX_WIDTH = 880

const DEPTH_LABELS: Record<TaskDepth, string> = {
  auto: '自动',
  brief: '简洁',
  longform: '长文',
}

interface SettingsRowProps {
  title: string
  description?: ReactNode
  control: ReactNode
}

/** 设置项：左侧标题与说明，右侧控件；窄屏自动换行。 */
function SettingsRow({ title, description, control }: SettingsRowProps) {
  return (
    <div className="settings-row">
      <div className="settings-row__text">
        <span className="settings-row__title">{title}</span>
        {description ? <span className="settings-row__desc">{description}</span> : null}
      </div>
      <div className="settings-row__control">{control}</div>
    </div>
  )
}

interface SettingsPageProps {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
}

/**
 * 设置页：集中管理「长期偏好」。
 *
 * 与工作台的边界：工作台上的执行深度 / 允许技能 / 检索范围是**本次任务参数**，
 * 这里决定的是它们要不要在下次进入工作台时自动套用，以及提醒类参数。
 * 所有数据只写 localStorage，不写入 SQLite `user_preferences`（那里是长期记忆）。
 */
export default function SettingsPage({ mode, setMode }: SettingsPageProps) {
  const { message } = App.useApp()
  const { pillSettings, updatePillSettings, clearAcknowledged } = useTaskRun()

  const [memory, setMemory] = useState<TaskOptionsMemory>(readTaskOptionsMemory)
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [documents, setDocuments] = useState<DocumentInfo[]>([])

  // 只为把记住的检索范围翻译成可读文案；失败时保留 id 兜底，不打扰用户。
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [categoryData, documentData] = await Promise.all([listCategories(), listDocuments()])
        if (cancelled) return
        setCategories(categoryData.categories)
        setDocuments(documentData.documents)
      } catch {
        // 忽略：范围摘要退化为 id 数量，不影响设置本身
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const handleRememberChange = useCallback(
    (checked: boolean) => {
      setMemory(setTaskOptionsRemember(checked))
      message.success(
        checked ? '已开启，进入工作台时会自动套用上次的选项' : '已关闭，记住的选项仍保留',
      )
    },
    [message],
  )

  const handleClearMemory = useCallback(() => {
    clearTaskOptionsMemory()
    setMemory(defaultTaskOptionsMemory())
    message.success('已清除记住的执行选项')
  }, [message])

  const handleClearAcknowledged = useCallback(() => {
    clearAcknowledged()
    message.success('已清除查看记录，最近结束的任务会重新出现在顶栏')
  }, [clearAcknowledged, message])

  const handleResetAll = useCallback(() => {
    clearTaskOptionsMemory()
    setMemory(defaultTaskOptionsMemory())
    clearAcknowledged()
    updatePillSettings(DEFAULT_PILL_SETTINGS)
    setMode('system')
    message.success('已恢复默认设置（主题改为跟随系统）')
  }, [clearAcknowledged, message, setMode, updatePillSettings])

  const scopeSummary = useMemo(() => {
    const { scope, dropped } = sanitizeScope(memory.options.scope, categories, documents)
    const description = describeScope(scope, categories, documents)
    const categoryTags = scope.category_ids.flatMap((id) => {
      const found = categories.find((item) => item.category_id === id)
      return found ? [{ id, name: found.name }] : []
    })
    return {
      bound: description.bound,
      label: description.label,
      documentCount: description.documentCount,
      categoryTags,
      individualDocuments: scope.document_ids.length,
      dropped,
    }
  }, [categories, documents, memory])

  const resolvedLabel = mode === 'system' ? '跟随系统' : mode === 'dark' ? '深色' : '浅色'
  const retrievalLabel =
    memory.options.retrievalMode === 'none'
      ? '不使用知识库'
      : memory.options.retrievalMode === 'all'
        ? '全部知识库'
        : scopeSummary.label

  return (
    <PageContainer
      eyebrow="设置"
      title="管理长期偏好与提醒"
      description="这些偏好只保存在当前浏览器。工作台上的执行深度、允许技能与检索范围属于本次任务参数，不会自动影响其它任务。"
      maxWidth={PAGE_MAX_WIDTH}
    >
      <Card title="外观">
        <SettingsRow
          title="主题"
          description={
            mode === 'system'
              ? '跟随系统时会实时响应系统的浅色 / 深色设置（顶栏按钮可快速切换为固定主题）。'
              : `当前固定为${resolvedLabel}；需要重新跟随系统请选择「跟随系统」。`
          }
          control={
            <Segmented
              value={mode}
              onChange={(value) => setMode(value as ThemeMode)}
              options={[
                { label: '跟随系统', value: 'system' },
                { label: '浅色', value: 'light' },
                { label: '深色', value: 'dark' },
              ]}
            />
          }
        />
      </Card>

      <Card title="工作台默认值">
        <SettingsRow
          title="记住上次的执行选项"
          description="开启后，进入工作台会自动套用上次的执行深度、技能开关与检索范围。关闭不会清空已记住的值，再次开启即可恢复。"
          control={
            <Switch
              checked={memory.remember}
              onChange={handleRememberChange}
              aria-label="记住上次的执行选项"
            />
          }
        />

        <div className="settings-summary">
          <div className="settings-summary__head">
            <span>当前记住的选项</span>
            {memory.remember ? <Tag color="green">已开启</Tag> : <Tag>未启用</Tag>}
          </div>
          <div className="settings-summary__row">
            <span className="settings-summary__label">执行深度</span>
            <span>{DEPTH_LABELS[memory.options.depth]}</span>
          </div>
          <div className="settings-summary__row">
            <span className="settings-summary__label">允许技能</span>
            <span>{memory.options.useSkills ? '允许' : '不允许'}</span>
          </div>
          <div className="settings-summary__row">
            <span className="settings-summary__label">检索范围</span>
            <span>{retrievalLabel}</span>
          </div>
          {memory.options.retrievalMode === 'selected' && scopeSummary.bound ? (
            <div className="settings-summary__row">
              <span className="settings-summary__label">范围明细</span>
              <span className="settings-summary__detail">
                {scopeSummary.categoryTags.length > 0 ? (
                  <>
                    {scopeSummary.categoryTags.map((item) => (
                      <Tag key={item.id}>{item.name}</Tag>
                    ))}
                  </>
                ) : null}
                {scopeSummary.individualDocuments > 0 ? (
                  <Tag>{scopeSummary.individualDocuments} 篇单独选择</Tag>
                ) : null}
                <Text type="secondary">共 {scopeSummary.documentCount} 篇文档</Text>
              </span>
            </div>
          ) : null}
          {memory.options.retrievalMode === 'selected' && scopeSummary.dropped > 0 ? (
            <Text type="secondary">
              有 {scopeSummary.dropped} 个类别 / 文档已被删除，恢复时会自动忽略。
            </Text>
          ) : null}
        </div>

        <div className="settings-actions">
          <Text type="secondary">
            工作台的改动会在提交任务时记录；开启记忆后也会随表单变化实时记录。
          </Text>
          <Button icon={<ClearOutlined />} onClick={handleClearMemory}>
            清除记住的选项
          </Button>
        </div>
      </Card>

      <Card title="任务提醒">
        <SettingsRow
          title="会话内最多保留"
          description="顶栏「完成待查看」胶囊的上限；超出后更早的任务自动标为已查看（失败任务永不自动丢弃）。调小后立即生效。"
          control={
            <InputNumber
              min={PILL_SETTING_RANGES.pendingLimit.min}
              max={PILL_SETTING_RANGES.pendingLimit.max}
              precision={0}
              value={pillSettings.pendingLimit}
              onChange={(value) =>
                updatePillSettings({
                  pendingLimit: value ?? PILL_SETTING_RANGES.pendingLimit.fallback,
                })
              }
              addonAfter="条"
            />
          }
        />
        <SettingsRow
          title="刷新后恢复窗口"
          description="刷新页面时只恢复这段时间内结束的任务，避免把很久以前的旧任务翻出来。下次刷新时生效。"
          control={
            <InputNumber
              min={PILL_SETTING_RANGES.restoreWindowHours.min}
              max={PILL_SETTING_RANGES.restoreWindowHours.max}
              precision={0}
              value={pillSettings.restoreWindowHours}
              onChange={(value) =>
                updatePillSettings({
                  restoreWindowHours: value ?? PILL_SETTING_RANGES.restoreWindowHours.fallback,
                })
              }
              addonAfter="小时"
            />
          }
        />
        <SettingsRow
          title="刷新后最多恢复"
          description="恢复窗口内最多显示几条未查看的完成态胶囊。下次刷新时生效。"
          control={
            <InputNumber
              min={PILL_SETTING_RANGES.restoreLimit.min}
              max={PILL_SETTING_RANGES.restoreLimit.max}
              precision={0}
              value={pillSettings.restoreLimit}
              onChange={(value) =>
                updatePillSettings({
                  restoreLimit: value ?? PILL_SETTING_RANGES.restoreLimit.fallback,
                })
              }
              addonAfter="条"
            />
          }
        />
        <div className="settings-actions">
          <Text type="secondary">调大上限不会恢复已经被自动归档的提醒。</Text>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              updatePillSettings(DEFAULT_PILL_SETTINGS)
              message.success('已恢复提醒默认值')
            }}
          >
            恢复默认
          </Button>
        </div>
      </Card>

      <Card title="本地数据">
        <SettingsRow
          title="清除「已查看」记录"
          description="清除后，最近结束（且仍在恢复窗口内）的任务会重新出现在顶栏胶囊里；任务记录与结果不受影响。"
          control={
            <Button icon={<DeleteOutlined />} onClick={handleClearAcknowledged}>
              清除记录
            </Button>
          }
        />
        <SettingsRow
          title="重置全部设置"
          description="主题恢复「跟随系统」，同时清除记住的执行选项、提醒参数与「已查看」记录。"
          control={
            <Popconfirm
              title="恢复到默认设置？"
              description="只会影响当前浏览器的界面偏好，不会删除任务、文档或长期记忆。"
              okText="恢复默认"
              cancelText="取消"
              onConfirm={handleResetAll}
            >
              <Button danger icon={<SettingOutlined />}>
                重置全部
              </Button>
            </Popconfirm>
          }
        />
        <div className="settings-actions">
          <Text type="secondary">
            以上数据仅存于当前浏览器（localStorage），不会写入长期记忆，也不会跨设备同步。
          </Text>
        </div>
      </Card>

      <Space size={4} wrap>
        <Text type="secondary">提示：顶栏的主题按钮会直接把主题切为固定的浅色 / 深色。</Text>
      </Space>
    </PageContainer>
  )
}
