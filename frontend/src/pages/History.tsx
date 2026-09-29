import { Alert, Button, Card, Descriptions, Drawer, Space, Table, Tag, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import MarkdownView from '../components/MarkdownView'
import { ApiError, getTask, getTaskState, listTasks } from '../services/api'
import type { TaskDetail, TaskState, TaskSummary } from '../types/api'

const { Text, Paragraph } = Typography

const STATUS_COLOR: Record<string, string> = {
  completed: 'green',
  running: 'blue',
  failed: 'red',
}

export default function HistoryPage() {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [state, setState] = useState<TaskState | null>(null)
  const [stateError, setStateError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listTasks()
      setTasks(data.tasks)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载任务历史失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const openDetail = async (taskId: string) => {
    setDetailLoading(true)
    setState(null)
    setStateError(null)
    try {
      setDetail(await getTask(taskId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载任务详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const loadState = async (taskId: string) => {
    setStateError(null)
    try {
      setState(await getTaskState(taskId))
    } catch (err) {
      setStateError(err instanceof ApiError ? err.message : '读取 checkpoint 失败')
    }
  }

  return (
    <Space
      orientation="vertical"
      size="middle"
      style={{ width: '100%', maxWidth: 1000, margin: '0 auto' }}
    >
      {error && <Alert type="error" showIcon title={error} />}

      <Card
        title={`任务历史（${tasks.length}）`}
        extra={<Button onClick={() => void refresh()} loading={loading}>刷新</Button>}
      >
        <Table<TaskSummary>
          rowKey="task_id"
          dataSource={tasks}
          loading={loading}
          pagination={false}
          locale={{ emptyText: '还没有任务记录' }}
          columns={[
            {
              title: '任务',
              dataIndex: 'query',
              key: 'query',
              ellipsis: true,
            },
            {
              title: '状态',
              dataIndex: 'status',
              key: 'status',
              width: 110,
              render: (status: string) => (
                <Tag color={STATUS_COLOR[status] ?? 'default'}>{status}</Tag>
              ),
            },
            {
              title: '未通过章节',
              dataIndex: 'failed_chapters',
              key: 'failed_chapters',
              width: 130,
              render: (chapters: string[]) =>
                chapters.length === 0 ? (
                  <Text type="secondary">—</Text>
                ) : (
                  <Text type="warning">{chapters.join(', ')}</Text>
                ),
            },
            {
              title: '创建时间',
              dataIndex: 'created_at',
              key: 'created_at',
              width: 200,
              render: (value: string) => <Text type="secondary">{value.replace('T', ' ')}</Text>,
            },
            {
              title: '操作',
              key: 'action',
              width: 90,
              render: (_, record) => (
                <Button type="link" onClick={() => void openDetail(record.task_id)}>
                  详情
                </Button>
              ),
            },
          ]}
        />
      </Card>

      <Drawer
        title={detail ? `任务详情 · ${detail.task_id.slice(0, 8)}` : '任务详情'}
        size={760}
        open={detail !== null}
        loading={detailLoading}
        onClose={() => setDetail(null)}
        destroyOnHidden
      >
        {detail && (
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="任务">{detail.query}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_COLOR[detail.status] ?? 'default'}>{detail.status}</Tag>
                {detail.error_type && <Tag color="red">{detail.error_type}</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="创建 / 完成">
                {detail.created_at.replace('T', ' ')} →{' '}
                {detail.finished_at ? detail.finished_at.replace('T', ' ') : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="重新规划次数">{detail.retry_count}</Descriptions.Item>
              <Descriptions.Item label="未通过校验章节">
                {detail.failed_chapters.length ? detail.failed_chapters.join(', ') : '无'}
              </Descriptions.Item>
            </Descriptions>

            <Card
              size="small"
              title="Agent Checkpoint 状态"
              extra={
                <Button size="small" onClick={() => void loadState(detail.task_id)}>
                  读取
                </Button>
              }
            >
              {stateError && <Paragraph type="danger">{stateError}</Paragraph>}
              {state ? (
                <Descriptions column={2} size="small">
                  <Descriptions.Item label="当前步骤">{state.current_step ?? '—'}</Descriptions.Item>
                  <Descriptions.Item label="是否完成">
                    {state.is_complete ? '是' : '否'}
                  </Descriptions.Item>
                  <Descriptions.Item label="已写章节">
                    {state.chapters_written}
                  </Descriptions.Item>
                  <Descriptions.Item label="检索片段">
                    {state.sources_count}
                  </Descriptions.Item>
                </Descriptions>
              ) : (
                <Text type="secondary">点击「读取」查看该任务的 checkpoint 结构化状态</Text>
              )}
            </Card>

            {detail.sources.length > 0 && (
              <Card size="small" title="参考来源">
                <ol style={{ paddingLeft: 20, margin: 0 }}>
                  {detail.sources.map((source) => (
                    <li key={source.chunk_id}>
                      [{source.index}] {source.filename}
                      {typeof source.score === 'number'
                        ? `（相似度 ${source.score.toFixed(3)}）`
                        : ''}
                    </li>
                  ))}
                </ol>
              </Card>
            )}

            <Card size="small" title="最终结果">
              {detail.final_answer ? (
                <MarkdownView content={detail.final_answer} />
              ) : (
                <Text type="secondary">该任务没有产出正文（可能失败或未完成）</Text>
              )}
            </Card>
          </Space>
        )}
      </Drawer>
    </Space>
  )
}
