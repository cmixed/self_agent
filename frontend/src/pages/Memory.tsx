import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  ImportOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
  Upload,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import ImportPreviewModal from '../components/ImportPreviewModal'
import PageContainer from '../components/PageContainer'
import {
  ApiError,
  addMemory,
  confirmMemoryImport,
  deleteMemory,
  deletePreference,
  exportMemory,
  getMemory,
  previewMemoryImport,
  setPreference,
} from '../services/api'
import type { MemoryImportPreview, MemoryProfile, MemoryRecord } from '../types/api'
import { downloadBlob } from '../utils/download'
import { formatDateTime } from '../utils/format'

const { Text, Paragraph } = Typography

const PAGE_EYEBROW = '长期记忆'
const PAGE_TITLE = '管理跨任务保留的偏好与信息'
const PAGE_DESCRIPTION =
  '偏好会在后续任务中按模式生效；事实与任务类型会作为相关任务的背景参考，不会被当作引用来源。'
const PAGE_MAX_WIDTH = 1200

/** 常用偏好键（与后端 MemoryService 的提示保持一致） */
const COMMON_KEYS = ['style', 'format', 'language', 'task_types']
// 偏好只走「偏好」通道；记忆存事实/任务类型，避免同一信息记两份
const MEMORY_KINDS = ['fact', 'task_type']

interface PreferenceRow {
  key: string
  value: string
}

export default function MemoryPage() {
  const { message } = App.useApp()
  const [profile, setProfile] = useState<MemoryProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [prefModalOpen, setPrefModalOpen] = useState(false)
  const [memModalOpen, setMemModalOpen] = useState(false)
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const [preferenceForm] = Form.useForm<{ key: string; value: string }>()
  const [memoryForm] = Form.useForm<{ kind: string; content: string }>()

  // --- 导入 / 导出 ---
  const [importing, setImporting] = useState(false)
  const [importPreview, setImportPreview] = useState<MemoryImportPreview | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setProfile(await getMemory())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载长期记忆失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // --- 偏好 ---
  const openAddPreference = () => {
    setEditingKey(null)
    preferenceForm.resetFields()
    setPrefModalOpen(true)
  }

  const openEditPreference = (key: string, value: string) => {
    setEditingKey(key)
    preferenceForm.setFieldsValue({ key, value })
    setPrefModalOpen(true)
  }

  const closePreferenceModal = () => {
    setPrefModalOpen(false)
    setEditingKey(null)
    preferenceForm.resetFields()
  }

  const handleSavePreference = async (values: { key: string; value: string }) => {
    setSaving(true)
    setError(null)
    try {
      await setPreference(values.key, values.value)
      message.success(editingKey ? `已更新偏好 ${values.key}` : `已设置偏好 ${values.key}`)
      closePreferenceModal()
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存偏好失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDeletePreference = async (key: string) => {
    setError(null)
    try {
      await deletePreference(key)
      message.success(`已删除偏好 ${key}`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除偏好失败')
    }
  }

  // --- 记忆 ---
  const openAddMemory = () => {
    memoryForm.resetFields()
    setMemModalOpen(true)
  }

  const closeMemoryModal = () => {
    setMemModalOpen(false)
    memoryForm.resetFields()
  }

  const handleAddMemory = async (values: { kind: string; content: string }) => {
    setSaving(true)
    setError(null)
    try {
      await addMemory(values.kind, values.content)
      message.success('已新增长期记忆')
      closeMemoryModal()
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '新增记忆失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteMemory = async (memoryId: number) => {
    setError(null)
    try {
      await deleteMemory(memoryId)
      message.success('已删除该记忆')
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除记忆失败')
    }
  }

  // --- 导入 / 导出 ---

  const handleImportFile = async (file: File) => {
    setImporting(true)
    setImportError(null)
    setImportPreview(null)
    try {
      setImportPreview(await previewMemoryImport(file))
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '解析记忆文件失败')
    } finally {
      setImporting(false)
    }
  }

  const handleConfirmImport = async () => {
    if (!importPreview) return
    setImporting(true)
    setImportError(null)
    try {
      const result = await confirmMemoryImport(importPreview.token)
      const skipped =
        result.skipped_preferences.length +
        result.skipped_memories.length +
        importPreview.skipped_preferences.length +
        importPreview.skipped_memories.length
      message.success(
        `已导入 ${result.preferences.length} 条偏好、${result.memories.length} 条记忆` +
          (skipped > 0 ? `，跳过 ${skipped} 条重复` : ''),
      )
      setImportPreview(null)
      await refresh()
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '导入记忆失败')
    } finally {
      setImporting(false)
    }
  }

  const handleExport = async () => {
    setError(null)
    try {
      const { blob, filename } = await exportMemory()
      downloadBlob(blob, filename)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '导出记忆失败')
    }
  }

  const closeImport = () => {
    if (importing) return
    setImportPreview(null)
    setImportError(null)
  }

  const preferences: PreferenceRow[] = Object.entries(profile?.preferences ?? {}).map(
    ([key, value]) => ({ key, value }),
  )
  const memories: MemoryRecord[] = profile?.memories ?? []
  const firstLoad = loading && profile === null

  return (
    <PageContainer
      eyebrow={PAGE_EYEBROW}
      title={PAGE_TITLE}
      description={PAGE_DESCRIPTION}
      maxWidth={PAGE_MAX_WIDTH}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>
            刷新
          </Button>
          <Upload
            accept=".json"
            showUploadList={false}
            beforeUpload={(file) => {
              void handleImportFile(file)
              return false
            }}
          >
            <Button icon={<ImportOutlined />} loading={importing}>
              导入记忆
            </Button>
          </Upload>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => void handleExport()}
            disabled={preferences.length === 0 && memories.length === 0}
          >
            导出记忆
          </Button>
        </Space>
      }
    >
      {error ? (
        <ErrorNotice
          message={error}
          onClose={() => setError(null)}
          onRetry={() => void refresh()}
        />
      ) : null}

      <Card
        title={`偏好（${preferences.length}）`}
        extra={
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openAddPreference}>
            新增偏好
          </Button>
        }
      >
        {firstLoad ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : preferences.length === 0 ? (
          <EmptyState
            title="还没有偏好设置"
            hint={`常用键：${COMMON_KEYS.join(' / ')}；也可以自由填写`}
          />
        ) : (
          <div className="kv-grid">
            {preferences.map((item) => (
              <div className="kv-card" key={item.key}>
                <div className="kv-card__head">
                  {COMMON_KEYS.includes(item.key) ? (
                    <Tag color="blue">{item.key}</Tag>
                  ) : (
                    <Tag>{item.key}</Tag>
                  )}
                  <Space size={2}>
                    <Button
                      type="text"
                      size="small"
                      aria-label={`编辑偏好 ${item.key}`}
                      icon={<EditOutlined />}
                      onClick={() => openEditPreference(item.key, item.value)}
                    />
                    <Popconfirm
                      title={`删除偏好 ${item.key}？`}
                      description="删除后任务将不再使用该偏好。"
                      onConfirm={() => void handleDeletePreference(item.key)}
                    >
                      <Button
                        type="text"
                        size="small"
                        danger
                        aria-label={`删除偏好 ${item.key}`}
                        icon={<DeleteOutlined />}
                      />
                    </Popconfirm>
                  </Space>
                </div>
                <div className="kv-card__value">{item.value}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card
        title={`记忆（${memories.length}）`}
        extra={
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openAddMemory}>
            新增记忆
          </Button>
        }
      >
        {firstLoad ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : memories.length === 0 ? (
          <EmptyState title="还没有长期记忆" hint="跑一次任务后系统会自动积累，也可以手动添加" />
        ) : (
          <div className="mem-grid">
            {memories.map((item) => (
              <div className="mem-card" key={item.memory_id}>
                <div className="mem-card__head">
                  <Tag>{item.kind}</Tag>
                  <Text type="secondary" className="mem-card__time">
                    {formatDateTime(item.created_at)}
                  </Text>
                </div>
                <div className="mem-card__content">{item.content}</div>
                <div className="mem-card__foot">
                  <Text type="secondary">
                    {item.source_task_id
                      ? `来自任务 ${item.source_task_id.slice(0, 8)}`
                      : '手动添加'}
                  </Text>
                  <Popconfirm
                    title="删除该记忆？"
                    description="删除后不可恢复。"
                    onConfirm={() => void handleDeleteMemory(item.memory_id)}
                  >
                    <Button
                      type="text"
                      size="small"
                      danger
                      aria-label="删除记忆"
                      icon={<DeleteOutlined />}
                    />
                  </Popconfirm>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Modal
        title={editingKey ? `编辑偏好 · ${editingKey}` : '新增偏好'}
        open={prefModalOpen}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        onOk={() => preferenceForm.submit()}
        onCancel={closePreferenceModal}
        destroyOnHidden
      >
        <Form
          form={preferenceForm}
          layout="vertical"
          onFinish={(values) => void handleSavePreference(values)}
        >
          <Form.Item name="key" label="键" rules={[{ required: true, message: '请输入键' }]}>
            <Input
              id="preference-key"
              name="key"
              placeholder="如 style"
              disabled={editingKey !== null}
            />
          </Form.Item>
          <Form.Item name="value" label="值" rules={[{ required: true, message: '请输入值' }]}>
            <Input id="preference-value" name="value" placeholder="如 偏好学术严谨" />
          </Form.Item>
        </Form>
        <div className="memory-form-hint">
          <Text type="secondary">快捷填入常用键：</Text>
          <Space size={[8, 8]} wrap>
            {COMMON_KEYS.map((key) => (
              <Button
                key={key}
                size="small"
                className="sample-chip"
                onClick={() => preferenceForm.setFieldsValue({ key })}
              >
                {key}
              </Button>
            ))}
          </Space>
        </div>
      </Modal>

      <Modal
        title="新增记忆"
        open={memModalOpen}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        onOk={() => memoryForm.submit()}
        onCancel={closeMemoryModal}
        destroyOnHidden
      >
        <Form
          form={memoryForm}
          layout="vertical"
          initialValues={{ kind: 'fact' }}
          onFinish={(values) => void handleAddMemory(values)}
        >
          <Form.Item name="kind" label="类型" rules={[{ required: true, message: '请选择类型' }]}>
            <Select
              id="memory-kind"
              options={MEMORY_KINDS.map((kind) => ({ label: kind, value: kind }))}
            />
          </Form.Item>
          <Form.Item
            name="content"
            label="内容"
            rules={[{ required: true, message: '请输入内容' }]}
          >
            <Input.TextArea
              id="memory-content"
              name="content"
              rows={3}
              placeholder="记忆内容，如：经常撰写技术综述"
            />
          </Form.Item>
        </Form>
      </Modal>

      <ImportPreviewModal
        open={importing || importPreview !== null || importError !== null}
        title="导入长期记忆"
        preview={importPreview}
        importing={importing}
        error={importError}
        confirmDisabled={
          (importPreview?.memories.length ?? 0) === 0 &&
          Object.keys(importPreview?.preferences ?? {}).length === 0
        }
        onCancel={closeImport}
        onConfirm={() => void handleConfirmImport()}
      >
        {importPreview ? (
          <>
            <Text type="secondary">
              将新增 {Object.keys(importPreview.preferences).length} 条偏好、
              {importPreview.memories.length} 条记忆
            </Text>
            {Object.keys(importPreview.preferences).length > 0 ? (
              <div>
                <Text strong>偏好</Text>
                <div className="kv-grid">
                  {Object.entries(importPreview.preferences).map(([key, value]) => (
                    <div className="kv-card" key={key}>
                      <div className="kv-card__head">
                        <Tag>{key}</Tag>
                      </div>
                      <div className="kv-card__value">{value}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {importPreview.memories.length > 0 ? (
              <div>
                <Text strong>记忆</Text>
                {importPreview.memories.map((item, index) => (
                  <Card size="small" key={`${item.kind}-${index}`}>
                    <Tag>{item.kind}</Tag>
                    <Paragraph style={{ marginBottom: 0 }}>{item.content}</Paragraph>
                  </Card>
                ))}
              </div>
            ) : null}
            {importPreview.skipped_preferences.length + importPreview.skipped_memories.length >
            0 ? (
              <Text type="secondary">
                已跳过 {importPreview.skipped_preferences.length} 条重复偏好、
                {importPreview.skipped_memories.length} 条重复记忆（已有内容优先保留）
              </Text>
            ) : null}
          </>
        ) : null}
      </ImportPreviewModal>
    </PageContainer>
  )
}
