import { Alert, Button, Card, Form, Input, Popconfirm, Space, Table, Tag, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError,
  addMemory,
  deleteMemory,
  deletePreference,
  getMemory,
  setPreference,
} from '../services/api'
import type { MemoryProfile, MemoryRecord } from '../types/api'

const { Text, Paragraph } = Typography

const COMMON_KEYS = ['style', 'format', 'language', 'task_types']

export default function MemoryPage() {
  const [profile, setProfile] = useState<MemoryProfile | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

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

  const run = async (action: () => Promise<unknown>, success: string) => {
    setError(null)
    setNotice(null)
    try {
      await action()
      setNotice(success)
      await refresh()
      return true
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
      return false
    }
  }

  const preferences = Object.entries(profile?.preferences ?? {}).map(([key, value]) => ({
    key,
    value,
  }))

  return (
    <Space
      orientation="vertical"
      size="middle"
      style={{ width: '100%', maxWidth: 900, margin: '0 auto' }}
    >
      <Alert
        type="info"
        showIcon
        title="长期记忆会跨会话生效：任务运行时会自动并入 Agent 的「用户偏好」"
        description="显式设置的值优先；任务完成后系统也会用 LLM 提取新偏好，但不会覆盖这里已有的键。"
      />

      {notice && <Alert type="success" showIcon title={notice} />}
      {error && <Alert type="error" showIcon title={error} />}

      <Card title={`偏好（${preferences.length}）`} loading={loading}>
        <Table
          rowKey="key"
          dataSource={preferences}
          pagination={false}
          size="small"
          locale={{ emptyText: '还没有偏好设置' }}
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
              width: 90,
              render: (_, record) => (
                <Popconfirm
                  title="删除该偏好？"
                  onConfirm={() =>
                    void run(() => deletePreference(record.key), `已删除偏好 ${record.key}`)
                  }
                >
                  <Button danger type="link">
                    删除
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />

        <Form
          form={preferenceForm}
          layout="inline"
          style={{ marginTop: 16, gap: 8 }}
          onFinish={(values) =>
            void run(
              () => setPreference(values.key, values.value),
              `已设置偏好 ${values.key}`,
            ).then((ok) => ok && preferenceForm.resetFields())
          }
        >
          <Form.Item name="key" rules={[{ required: true, message: '请输入键' }]}>
            <Input placeholder="键，如 style" style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="value" rules={[{ required: true, message: '请输入值' }]}>
            <Input placeholder="值，如 偏好学术严谨" style={{ width: 280 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              保存偏好
            </Button>
          </Form.Item>
        </Form>
        <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
          常用键：{COMMON_KEYS.join(' / ')}
        </Paragraph>
      </Card>

      <Card title={`记忆（${profile?.memories.length ?? 0}）`} loading={loading}>
        <Table<MemoryRecord>
          rowKey="memory_id"
          dataSource={profile?.memories ?? []}
          pagination={false}
          size="small"
          locale={{ emptyText: '还没有长期记忆' }}
          columns={[
            {
              title: '类型',
              dataIndex: 'kind',
              key: 'kind',
              width: 120,
              render: (kind: string) => <Tag>{kind}</Tag>,
            },
            { title: '内容', dataIndex: 'content', key: 'content' },
            {
              title: '来源任务',
              dataIndex: 'source_task_id',
              key: 'source_task_id',
              width: 110,
              render: (value: string | null) =>
                value ? <Text code>{value.slice(0, 8)}</Text> : <Text type="secondary">手动</Text>,
            },
            {
              title: '操作',
              key: 'action',
              width: 90,
              render: (_, record) => (
                <Popconfirm
                  title="删除该记忆？"
                  onConfirm={() =>
                    void run(() => deleteMemory(record.memory_id), '已删除该记忆')
                  }
                >
                  <Button danger type="link">
                    删除
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />

        <Form
          form={memoryForm}
          layout="inline"
          style={{ marginTop: 16, gap: 8 }}
          onFinish={(values) =>
            void run(
              () => addMemory(values.kind, values.content),
              '已新增长期记忆',
            ).then((ok) => ok && memoryForm.resetFields())
          }
        >
          <Form.Item name="kind" initialValue="fact" rules={[{ required: true }]}>
            <Input placeholder="类型，如 fact" style={{ width: 130 }} />
          </Form.Item>
          <Form.Item name="content" rules={[{ required: true, message: '请输入内容' }]}>
            <Input placeholder="记忆内容" style={{ width: 320 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              新增记忆
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </Space>
  )
}
