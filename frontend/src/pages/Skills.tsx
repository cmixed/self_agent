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
  Switch,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import PageContainer from '../components/PageContainer'
import {
  ApiError,
  createSkill,
  deleteSkill,
  listSkills,
  updateSkill,
} from '../services/api'
import type { SkillInfo } from '../types/api'
import { formatDateTime } from '../utils/format'

const { Text, Paragraph } = Typography

const PAGE_EYEBROW = '技能'
const PAGE_TITLE = '让 Agent 在任务中调用你的技能'
const PAGE_DESCRIPTION =
  '技能是 Agent 可调用的结构化指令：规划阶段会看到技能目录，命中时按技能说明产出分析结论，供后续写作使用。'
const PAGE_MAX_WIDTH = 1200

interface SkillFormValues {
  name: string
  description: string
  content: string
}

export default function SkillsPage() {
  const { message } = App.useApp()
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<SkillInfo | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<SkillFormValues>()

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listSkills()
      setSkills(data.skills)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载技能失败')
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

  const openEdit = (skill: SkillInfo) => {
    setEditing(skill)
    form.setFieldsValue({
      name: skill.name,
      description: skill.description,
      content: skill.content,
    })
    setModalOpen(true)
  }

  const closeModal = () => {
    setModalOpen(false)
    setEditing(null)
    form.resetFields()
  }

  const handleSave = async (values: SkillFormValues) => {
    setSaving(true)
    setError(null)
    try {
      if (editing) {
        await updateSkill(editing.skill_id, values)
        message.success(`已更新技能「${values.name}」`)
      } else {
        await createSkill(values)
        message.success(`已创建技能「${values.name}」`)
      }
      closeModal()
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存技能失败')
    } finally {
      setSaving(false)
    }
  }

  const handleToggle = async (skill: SkillInfo, enabled: boolean) => {
    setError(null)
    try {
      const updated = await updateSkill(skill.skill_id, { enabled })
      setSkills((prev) =>
        prev.map((item) => (item.skill_id === updated.skill_id ? updated : item)),
      )
      message.success(enabled ? `已启用「${skill.name}」` : `已停用「${skill.name}」`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '更新技能状态失败')
    }
  }

  const handleDelete = async (skill: SkillInfo) => {
    setError(null)
    try {
      await deleteSkill(skill.skill_id)
      message.success(`已删除技能「${skill.name}」`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除技能失败')
    }
  }

  const firstLoad = loading && skills.length === 0
  const enabledCount = skills.filter((skill) => skill.enabled).length

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
            新建技能
          </Button>
        </Space>
      }
    >
      {error ? (
        <ErrorNotice message={error} onClose={() => setError(null)} onRetry={() => void refresh()} />
      ) : null}

      <Card title={`技能库（${skills.length}｜启用 ${enabledCount}）`}>
        {firstLoad ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : skills.length === 0 ? (
          <EmptyState
            title="还没有技能"
            hint="新建一个技能，描述 Agent 在该场景下应当怎么做"
          />
        ) : (
          <div className="entity-list">
            {skills.map((skill) => (
              <div className="entity-item" key={skill.skill_id}>
                <div className="entity-item__main">
                  <div className="entity-item__head">
                    <Text strong>{skill.name}</Text>
                    {skill.builtin ? <Tag>内置</Tag> : null}
                    {!skill.enabled ? <Tag color="default">已停用</Tag> : null}
                  </div>
                  <Paragraph type="secondary" className="entity-item__desc" ellipsis={{ rows: 2 }}>
                    {skill.description}
                  </Paragraph>
                  <Text type="secondary" className="entity-item__meta">
                    更新于 {formatDateTime(skill.updated_at)}
                  </Text>
                </div>
                <Space className="entity-item__actions">
                  <Tooltip title={skill.enabled ? '停用后不再进入 Agent 技能目录' : '启用后可被 Agent 调用'}>
                    <Switch
                      size="small"
                      checked={skill.enabled}
                      onChange={(checked) => void handleToggle(skill, checked)}
                    />
                  </Tooltip>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(skill)}>
                    编辑
                  </Button>
                  {skill.builtin ? (
                    <Tooltip title="内置技能不可删除，可编辑或停用">
                      <Button size="small" icon={<DeleteOutlined />} disabled />
                    </Tooltip>
                  ) : (
                    <Popconfirm
                      title={`删除技能「${skill.name}」？`}
                      description="删除后无法恢复"
                      okText="删除"
                      cancelText="取消"
                      onConfirm={() => void handleDelete(skill)}
                    >
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  )}
                </Space>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Modal
        title={editing ? `编辑技能：${editing.name}` : '新建技能'}
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
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入技能名称' }, { max: 60 }]}
          >
            <Input placeholder="例如：对比分析" />
          </Form.Item>
          <Form.Item
            name="description"
            label="适用场景"
            rules={[{ required: true, message: '请说明什么时候使用该技能' }, { max: 200 }]}
            extra="Planner 依据这句话判断是否调用该技能，请写清触发条件"
          >
            <Input placeholder="例如：当任务需要比较资料中的多个技术方案时使用" />
          </Form.Item>
          <Form.Item
            name="content"
            label="技能指令"
            rules={[{ required: true, message: '请输入技能指令' }]}
            extra="技能执行时作为 system 指令，指导 Agent 如何产出结论"
          >
            <Input.TextArea
              autoSize={{ minRows: 6, maxRows: 16 }}
              placeholder="你是……专家。请基于给定资料：1) …… 2) ……"
            />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  )
}
