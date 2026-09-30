import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Form,
  Input,
  List,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import PageContainer from '../components/PageContainer'
import {
  ApiError,
  addMemory,
  deleteMemory,
  deletePreference,
  getMemory,
  setPreference,
} from '../services/api'
import type { MemoryProfile, MemoryRecord } from '../types/api'
import { formatDateTime } from '../utils/format'

const { Text } = Typography

const PAGE_TITLE = '长期记忆'
const PAGE_DESCRIPTION = '跨会话生效的偏好与记忆：任务运行时会自动注入，显式设置的值优先。'
const PAGE_MAX_WIDTH = 1200

/** 常用偏好键（与后端 MemoryService 的提示保持一致） */
const COMMON_KEYS = ['style', 'format', 'language', 'task_types']
const MEMORY_KINDS = ['preference', 'fact', 'task_type']

interface PreferenceRow {
  key: string
  value: string
}

export default function MemoryPage() {
  const { message } = App.useApp()
  const [profile, setProfile] = useState<MemoryProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingKey, setEditingKey] = useState<string | null>(null)

  const [preferenceForm] = Form.useForm<{ key: string; value: string }>()
  const [memoryForm] = Form.useForm<{ kind: string; content: string }>()

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

  const handleSavePreference = async (values: { key: string; value: string }) => {
    setError(null)
    try {
      await setPreference(values.key, values.value)
      message.success(editingKey ? `已更新偏好 ${values.key}` : `已设置偏好 ${values.key}`)
      setEditingKey(null)
      preferenceForm.resetFields()
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存偏好失败')
    }
  }

  const handleDeletePreference = async (key: string) => {
    setError(null)
    try {
      await deletePreference(key)
      message.success(`已删除偏好 ${key}`)
      if (editingKey === key) {
        setEditingKey(null)
        preferenceForm.resetFields()
      }
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除偏好失败')
    }
  }

  const handleAddMemory = async (values: { kind: string; content: string }) => {
    setError(null)
    try {
      await addMemory(values.kind, values.content)
      message.success('已新增长期记忆')
      memoryForm.resetFields()
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '新增记忆失败')
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

  const startEditing = (key: string, value: string) => {
    setEditingKey(key)
    preferenceForm.setFieldsValue({ key, value })
  }

  const preferences: PreferenceRow[] = Object.entries(profile?.preferences ?? {}).map(
    ([key, value]) => ({ key, value }),
  )
  const memories = profile?.memories ?? []
  const firstLoad = loading && profile === null

  return (
    <PageContainer
      title={PAGE_TITLE}
      description={PAGE_DESCRIPTION}
      maxWidth={PAGE_MAX_WIDTH}
      extra={
        <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>
          刷新
        </Button>
      }
    >
      {error && <ErrorNotice message={error} onClose={() => setError(null)} onRetry={() => void refresh()} />}

      <Card title={`偏好（${preferences.length}）`}>
        {firstLoad ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : preferences.length === 0 ? (
          <EmptyState
            title="还没有偏好设置"
            hint={
              <>
                常用键：{COMMON_KEYS.join(' / ')}；也可以在下方表单里自由填写
              </>
            }
          />
        ) : (
          <Table<PreferenceRow>
            rowKey="key"
            dataSource={preferences}
            pagination={false}
            size="small"
            scroll={{ x: 'max-content' }}
            columns={[
              {
                title: '键',
                dataIndex: 'key',
                key: 'key',
                width: 160,
                render: (key: string) =>
                  COMMON_KEYS.includes(key) ? <Tag color="blue">{key}</Tag> : <Tag>{key}</Tag>,
              },
              { title: '值', dataIndex: 'value', key: 'value' },
              {
                title: '操作',
                key: 'action',
                width: 130,
                render: (_, record) => (
                  <Space size={4}>
                    <Button type="link" onClick={() => startEditing(record.key, record.value)}>
                      编辑
                    </Button>
                    <Popconfirm
                      title={`删除偏好 ${record.key}？`}
                      description="删除后任务将不再使用该偏好。"
                      onConfirm={() => void handleDeletePreference(record.key)}
                    >
                      <Button danger type="link">
                        删除
                      </Button>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        )}

        <Form
          form={preferenceForm}
          layout="vertical"
          className="memory-form"
          onFinish={(values) => void handleSavePreference(values)}
        >
          <div className="memory-form__grid">
            <Form.Item name="key" label="键" rules={[{ required: true, message: '请输入键' }]}>
              <Input id="preference-key" name="key" placeholder="如 style" />
            </Form.Item>
            <Form.Item name="value" label="值" rules={[{ required: true, message: '请输入值' }]}>
              <Input id="preference-value" name="value" placeholder="如 偏好学术严谨" />
            </Form.Item>
          </div>
          <Form.Item className="memory-form__actions">
            <Space>
              <Button type="primary" htmlType="submit" icon={editingKey ? undefined : <PlusOutlined />}>
                {editingKey ? `保存修改（${editingKey}）` : '保存偏好'}
              </Button>
              {editingKey && (
                <Button
                  onClick={() => {
                    setEditingKey(null)
                    preferenceForm.resetFields()
                  }}
                >
                  取消编辑
                </Button>
              )}
            </Space>
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
      </Card>

      <Card title={`记忆（${memories.length}）`}>
        {firstLoad ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : (
          <List<MemoryRecord>
            dataSource={memories}
            locale={{
              emptyText: (
                <EmptyState
                  compact
                  title="还没有长期记忆"
                  hint="跑一次任务后系统会自动积累，也可以手动添加"
                />
              ),
            }}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Popconfirm
                    key="delete"
                    title="删除该记忆？"
                    description="删除后不可恢复。"
                    onConfirm={() => void handleDeleteMemory(item.memory_id)}
                  >
                    <Button danger type="link">
                      删除
                    </Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space size={6} wrap>
                      <Tag>{item.kind}</Tag>
                      <Text>{item.content}</Text>
                    </Space>
                  }
                  description={
                    <Text type="secondary">
                      {item.source_task_id ? `来自任务 ${item.source_task_id.slice(0, 8)}` : '手动添加'}
                      {' · '}
                      {formatDateTime(item.created_at)}
                    </Text>
                  }
                />
              </List.Item>
            )}
          />
        )}

        <Form
          form={memoryForm}
          layout="vertical"
          className="memory-form"
          initialValues={{ kind: 'fact' }}
          onFinish={(values) => void handleAddMemory(values)}
        >
          <div className="memory-form__grid memory-form__grid--memory">
            <Form.Item name="kind" label="类型" rules={[{ required: true, message: '请选择类型' }]}>
              <Select
                id="memory-kind"
                options={MEMORY_KINDS.map((kind) => ({ label: kind, value: kind }))}
              />
            </Form.Item>
            <Form.Item name="content" label="内容" rules={[{ required: true, message: '请输入内容' }]}>
              <Input
                id="memory-content"
                name="content"
                placeholder="记忆内容，如：经常撰写技术综述"
              />
            </Form.Item>
          </div>
          <Form.Item className="memory-form__actions">
            <Button type="primary" htmlType="submit" icon={<PlusOutlined />}>
              新增记忆
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </PageContainer>
  )
}
