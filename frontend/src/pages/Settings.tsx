import {
  BgColorsOutlined,
  BellOutlined,
  ClearOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  DownloadOutlined,
  ImportOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Segmented,
  Space,
  Switch,
  Tag,
  Typography,
  Upload,
} from 'antd'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import ImportPreviewModal from '../components/ImportPreviewModal'
import PageContainer from '../components/PageContainer'
import PageTabs from '../components/PageTabs'
import { setCachedPresets } from '../hooks/usePresets'
import {
  ApiError,
  confirmBackupImport,
  exportBackup,
  listCategories,
  listDocuments,
  listPresets,
  previewBackupImport,
} from '../services/api'
import { changePassword, getCachedUser } from '../services/auth'
import { useTaskRun } from '../state/taskRun'
import { useShortcuts } from '../state/shortcuts'
import type { ThemeMode } from '../theme/config'
import type { BackupImportPreview, CategoryInfo, DocumentInfo, TaskDepth } from '../types/api'
import { downloadBlob } from '../utils/download'
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

const PAGE_MAX_WIDTH = 1080

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
  /** 顶栏右侧板块切换胶囊是否显示（设置页可关） */
  showPageSwitcher: boolean
  setShowPageSwitcher: (visible: boolean) => void
}

/**
 * 设置页：集中管理「长期偏好」。
 *
 * 与工作台的边界：工作台上的执行深度 / 允许技能 / 检索范围是**本次任务参数**，
 * 这里决定的是它们要不要在下次进入工作台时自动套用，以及提醒类参数。
 * 所有数据只写 localStorage，不写入 SQLite `user_preferences`（那里是长期记忆）。
 */
export default function SettingsPage({
  mode,
  setMode,
  showPageSwitcher,
  setShowPageSwitcher,
}: SettingsPageProps) {
  const { message, modal } = App.useApp()
  const { pillSettings, updatePillSettings, clearAcknowledged } = useTaskRun()
  const { setSearchOpen } = useShortcuts()

  const [memory, setMemory] = useState<TaskOptionsMemory>(readTaskOptionsMemory)
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [documents, setDocuments] = useState<DocumentInfo[]>([])

  // --- 一键备份 / 恢复 ---
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importPreview, setImportPreview] = useState<BackupImportPreview | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

  // --- 分区导航与账号 ---
  const [section, setSection] = useState('appearance')
  const [pwdSaving, setPwdSaving] = useState(false)
  const [pwdForm] = Form.useForm<{ oldPassword: string; newPassword: string; confirm: string }>()
  const me = getCachedUser()

  const refreshLibrary = useCallback(async () => {
    try {
      const [categoryData, documentData] = await Promise.all([listCategories(), listDocuments()])
      setCategories(categoryData.categories)
      setDocuments(documentData.documents)
    } catch {
      // 忽略：范围摘要退化为 id 数量，不影响设置本身
    }
  }, [])

  // 只为把记住的检索范围翻译成可读文案；失败时保留 id 兜底，不打扰用户。
  useEffect(() => {
    void refreshLibrary()
  }, [refreshLibrary])

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

  const handleExportAll = async () => {
    setExporting(true)
    try {
      const { blob, filename } = await exportBackup()
      downloadBlob(blob, filename)
      message.success('已导出完整备份')
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '导出备份失败')
    } finally {
      setExporting(false)
    }
  }

  const handleImportAllFile = async (file: File) => {
    setImporting(true)
    setImportError(null)
    setImportPreview(null)
    try {
      setImportPreview(await previewBackupImport(file))
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '解析备份文件失败')
    } finally {
      setImporting(false)
    }
  }

  const handleConfirmImportAll = async () => {
    if (!importPreview) return
    setImporting(true)
    setImportError(null)
    try {
      const result = await confirmBackupImport(importPreview.token)
      const failed = result.sections.flatMap((section) =>
        section.failed.map((item) => `${section.label}：${item}`),
      )
      if (failed.length > 0) {
        modal.warning({
          title: '备份已恢复，但部分内容失败',
          content: (
            <ul className="plain-list">
              {failed.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ),
        })
      } else {
        message.success('已恢复全部备份')
      }
      setImportPreview(null)
      await refreshLibrary()
      try {
        const presetData = await listPresets()
        setCachedPresets(presetData.presets)
      } catch {
        // 缓存刷新失败不影响导入结果；工作台下次进入时会重新拉取
      }
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '恢复备份失败')
    } finally {
      setImporting(false)
    }
  }

  const closeImportAll = () => {
    if (importing) return
    setImportPreview(null)
    setImportError(null)
  }

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

  const handleChangePassword = async (values: { oldPassword: string; newPassword: string }) => {
    setPwdSaving(true)
    try {
      await changePassword(values.oldPassword, values.newPassword)
      pwdForm.resetFields()
      message.success('密码已更新')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '修改失败')
    } finally {
      setPwdSaving(false)
    }
  }

  const sections = [
    { key: 'appearance', label: '外观', icon: <BgColorsOutlined /> },
    { key: 'workspace', label: '工作台', icon: <ThunderboltOutlined /> },
    { key: 'reminder', label: '提醒', icon: <BellOutlined /> },
    { key: 'data', label: '数据', icon: <DatabaseOutlined /> },
    { key: 'account', label: '账号与安全', icon: <UserOutlined /> },
  ]

  const appearanceCard = (
    <>
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
        <SettingsRow
          title="顶栏板块切换"
          description="在顶栏右侧显示一排板块图标胶囊，用于快速切换页面；与左侧导航、G + 字母快捷键等价。关闭后只保留左侧导航，顶栏更简洁。"
          control={
            <Switch
              checked={showPageSwitcher}
              onChange={setShowPageSwitcher}
              aria-label="显示顶栏板块切换胶囊"
            />
          }
        />
      </Card>

      <Card title="搜索">
        <SettingsRow
          title="全局搜索"
          description="搜索页面、知识库与快捷键。入口只在设置页提供；顶栏与 dock 不再占用全局搜索，dock 的搜索按钮只调用当前页面的页内搜索。"
          control={
            <Button icon={<SearchOutlined />} onClick={() => setSearchOpen(true)}>
              打开全局搜索
            </Button>
          }
        />
      </Card>
    </>
  )

  const workspaceCard = (
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
  )

  const reminderCard = (
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
  )

  const dataCards = (
    <>
      <Card title="数据备份">
        <SettingsRow
          title="一键全部导出"
          description="把知识库、预设、长期记忆与自定义技能打包为一个 zip 备份文件。"
          control={
            <Button
              icon={<DownloadOutlined />}
              loading={exporting}
              onClick={() => void handleExportAll()}
            >
              导出完整备份
            </Button>
          }
        />
        <SettingsRow
          title="一键全部导入"
          description="上传完整备份；会先预览各部分的导入数量与重复项，确认后才写入。"
          control={
            <Upload
              accept=".zip"
              showUploadList={false}
              beforeUpload={(file) => {
                void handleImportAllFile(file)
                return false
              }}
            >
              <Button icon={<ImportOutlined />} loading={importing} disabled={importing}>
                选择备份文件
              </Button>
            </Upload>
          }
        />
        <div className="settings-actions">
          <Text type="secondary">
            包含：知识库、预设、长期记忆、自定义技能。不包含：内置技能、任务历史、LLM
            密钥与浏览器本地设置。导入知识库会重新建立向量索引，可能需要一些时间。
          </Text>
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
    </>
  )

  const accountCards = (
    <>
      <Card
        title="账号信息"
        extra={
          <Tag color={me?.role === 'admin' ? 'blue' : undefined}>
            {me?.role === 'admin' ? '管理员' : '成员'}
          </Tag>
        }
      >
        <SettingsRow
          title="用户名"
          description="登录使用的账号，创建后不可修改。"
          control={<Text>{me?.username ?? '—'}</Text>}
        />
        <SettingsRow title="显示名" control={<Text>{me?.display_name ?? '—'}</Text>} />
        <SettingsRow
          title="邮箱"
          description="绑定后可用于自助重置密码。"
          control={me?.email ? <Text>{me.email}</Text> : <Text type="secondary">未绑定</Text>}
        />
        <SettingsRow
          title="最近登录"
          control={
            <Text type="secondary">
              {me?.last_login_at ? me.last_login_at.slice(0, 16).replace('T', ' ') : '—'}
            </Text>
          }
        />
      </Card>

      <Card title="修改密码">
        <Form
          form={pwdForm}
          layout="vertical"
          requiredMark={false}
          style={{ maxWidth: 420 }}
          onFinish={handleChangePassword}
        >
          <Form.Item
            label="当前密码"
            name="oldPassword"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password autoComplete="current-password" placeholder="当前登录密码" />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="newPassword"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, message: '至少 8 位' },
            ]}
          >
            <Input.Password autoComplete="new-password" placeholder="至少 8 位" />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirm"
            dependencies={['newPassword']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator: (_, value) =>
                  !value || getFieldValue('newPassword') === value
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入不一致')),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" placeholder="再次输入新密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={pwdSaving}>
            更新密码
          </Button>
        </Form>
      </Card>
    </>
  )

  return (
    <PageContainer
      eyebrow="设置"
      title="管理长期偏好与提醒"
      description="这些偏好只保存在当前浏览器。工作台上的执行深度、允许技能与检索范围属于本次任务参数，不会自动影响其它任务。"
      maxWidth={PAGE_MAX_WIDTH}
    >
      <PageTabs
        label="设置分区"
        activeKey={section}
        onChange={setSection}
        items={sections.map((item) => ({
          key: item.key,
          label: (
            <>
              {item.icon}
              {item.label}
            </>
          ),
        }))}
      />

      {section === 'appearance' ? appearanceCard : null}
      {section === 'workspace' ? workspaceCard : null}
      {section === 'reminder' ? reminderCard : null}
      {section === 'data' ? dataCards : null}
      {section === 'account' ? accountCards : null}

      <ImportPreviewModal
        open={importing || importPreview !== null || importError !== null}
        title="恢复全部备份"
        preview={importPreview}
        importing={importing}
        error={importError}
        confirmDisabled={(importPreview?.sections.length ?? 0) === 0}
        onCancel={closeImportAll}
        onConfirm={() => void handleConfirmImportAll()}
      >
        {importPreview ? (
          <>
            <Alert
              type="warning"
              showIcon
              message="恢复会写入知识库、技能、预设与长期记忆"
              description="已有数据不会删除，重复项会跳过；知识库文档会重新解析并建立向量索引，可能需要一些时间。"
            />
            {importPreview.sections.map((section) => (
              <Card size="small" key={section.key}>
                <Space size={8} wrap>
                  <Text strong>{section.label}</Text>
                  <Text type="secondary">{section.summary}</Text>
                </Space>
              </Card>
            ))}
          </>
        ) : null}
      </ImportPreviewModal>
    </PageContainer>
  )
}
