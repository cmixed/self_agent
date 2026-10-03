import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Skeleton,
  Space,
  Typography,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import PageContainer from '../components/PageContainer'
import {
  ApiError,
  createPreset,
  deletePreset,
  listPresets,
  updatePreset,
} from '../services/api'
import type { PresetInfo } from '../types/api'
import { formatDateTime } from '../utils/format'

const { Text, Paragraph } = Typography

const PAGE_EYEBROW = '预设任务'
const PAGE_TITLE = '管理工作台的快捷任务'
const PAGE_DESCRIPTION =
  '预设会显示在工作台，点击即可填入输入框或一键直接运行；这里可以自由新增、编辑与删除。'
const PAGE_MAX_WIDTH = 1200

interface PresetFormValues {
  title: string
  description: string
  query: string
}

export default function PresetsPage() {
  const { message } = App.useApp()
  const [presets, setPresets] = useState<PresetInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<PresetInfo | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<PresetFormValues>()

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listPresets()
      setPresets(data.presets)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载预设任务失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (preset: PresetInfo) => {
    setEditing(preset)
    form.setFieldsValue({
      title: preset.title,
      description: preset.description,
      query: preset.query,
    })
    setModalOpen(true)
  }

  const closeModal = () => {
    setModalOpen(false)
    setEditing(null)
    form.resetFields()
  }

  const handleSave = async (values: PresetFormValues) => {
    setSaving(true)
    setError(null)
    try {
      if (editing) {
        await updatePreset(editing.preset_id, values)
        message.success(`已更新预设「${values.title}」`)
      } else {
        await createPreset(values)
        message.success(`已新增预设「${values.title}」`)
      }
      closeModal()
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存预设失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (preset: PresetInfo) => {
    setError(null)
    try {
      await deletePreset(preset.preset_id)
      message.success(`已删除预设「${preset.title}」`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除预设失败')
    }
  }

  const firstLoad = loading && presets.length === 0

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
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增预设
          </Button>
        </Space>
      }
    >
      {error ? (
        <ErrorNotice message={error} onClose={() => setError(null)} onRetry={() => void refresh()} />
      ) : null}

      <Card title={`预设（${presets.length}）`}>
        {firstLoad ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : presets.length === 0 ? (
          <EmptyState
            title="还没有预设任务"
            hint="新增一条预设，工作台就会出现对应的一键任务"
          />
        ) : (
          <div className="entity-list">
            {presets.map((preset) => (
              <div className="entity-item" key={preset.preset_id}>
                <div className="entity-item__main">
                  <Text strong>{preset.title}</Text>
                  <Paragraph type="secondary" className="entity-item__desc" ellipsis={{ rows: 2 }}>
                    {preset.description}
                  </Paragraph>
                  <Text code className="entity-item__query">
                    {preset.query}
                  </Text>
                  <Text type="secondary" className="entity-item__meta">
                    更新于 {formatDateTime(preset.updated_at)}
                  </Text>
                </div>
                <Space className="entity-item__actions">
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(preset)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title={`删除预设「${preset.title}」？`}
                    description="删除后工作台不再显示该预设"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={() => void handleDelete(preset)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Modal
        title={editing ? `编辑预设：${editing.title}` : '新增预设'}
        open={modalOpen}
        onCancel={closeModal}
        onOk={() => form.submit()}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={640}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(values) => void handleSave(values)}>
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: '请输入标题' }, { max: 40 }]}
          >
            <Input placeholder="例如：技术方案对比报告" />
          </Form.Item>
          <Form.Item
            name="description"
            label="说明"
            rules={[{ required: true, message: '请输入说明' }, { max: 120 }]}
            extra="显示在卡片上，用于说明这个预设会做什么"
          >
            <Input placeholder="例如：调研资料中的技术方案，输出对比与选型建议" />
          </Form.Item>
          <Form.Item
            name="query"
            label="任务内容"
            rules={[{ required: true, message: '请输入任务内容' }, { max: 2000 }]}
            extra="点击预设时提交给 Agent 的完整任务描述"
          >
            <Input.TextArea
              autoSize={{ minRows: 4, maxRows: 10 }}
              placeholder="例如：调研我资料里的几种技术方案，输出对比报告并给出选型建议"
            />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  )
}
