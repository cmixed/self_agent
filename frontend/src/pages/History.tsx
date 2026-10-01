import { CopyOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Input,
  Row,
  Segmented,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import { useDocumentWorkspace } from '../components/DocumentWorkspace'
import MarkdownReader from '../components/MarkdownReader'
import PageContainer from '../components/PageContainer'
import StatusTag from '../components/StatusTag'
import { ApiError, getTask, getTaskState, listTasks } from '../services/api'
import type { TaskDetail, TaskState, TaskSummary } from '../types/api'
import { downloadMarkdown } from '../utils/download'
import { formatDateTime, formatDuration, taskDurationSeconds } from '../utils/format'

const { Text } = Typography

const PAGE_EYEBROW = '任务历史'
const PAGE_TITLE = '查看过去任务的执行状态与结果'
const PAGE_DESCRIPTION = '支持按状态筛选；点击任务可查看正文、来源与校验结论。'
const PAGE_MAX_WIDTH = 1200

export default function HistoryPage() {
  const { message } = App.useApp()
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')

  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [state, setState] = useState<TaskState | null>(null)
  const [stateError, setStateError] = useState<string | null>(null)

  const { hasDocument } = useDocumentWorkspace()

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

    // 打开详情即自动读取 Agent checkpoint 状态（失败时给出可读提示）
    try {
      setState(await getTaskState(taskId))
    } catch (err) {
      setStateError(
        err instanceof ApiError
          ? err.status === 503
            ? '后端未启用 Checkpoint'
            : '该任务没有可读取的 Checkpoint 记录'
          : '读取 Checkpoint 失败',
      )
    }
  }

  const copyAnswer = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content)
      message.success('已复制到剪贴板')
    } catch {
      setError('复制失败（浏览器未授权剪贴板），请手动选择文本复制')
    }
  }

  const visibleTasks = tasks.filter((task) => {
    if (statusFilter !== 'all' && task.status !== statusFilter) return false
    if (keyword.trim() && !task.query.toLowerCase().includes(keyword.trim().toLowerCase())) {
      return false
    }
    return true
  })

  const counts = {
    all: tasks.length,
    running: tasks.filter((task) => task.status === 'running').length,
    completed: tasks.filter((task) => task.status === 'completed').length,
    cancelled: tasks.filter((task) => task.status === 'cancelled').length,
    failed: tasks.filter((task) => task.status === 'failed').length,
  }

  return (
    <PageContainer
      eyebrow={PAGE_EYEBROW}
      title={PAGE_TITLE}
      description={PAGE_DESCRIPTION}
      maxWidth={PAGE_MAX_WIDTH}
      extra={
        <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>
          刷新
        </Button>
      }
    >
      {error && (
        <ErrorNotice
          message={error}
          onClose={() => setError(null)}
          onRetry={() => void refresh()}
        />
      )}

      <Card title={`任务历史（${tasks.length}）`}>
        <div className="table-toolbar">
          <Input.Search
            id="history-search"
            name="keyword"
            allowClear
            placeholder="搜索任务内容"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            style={{ maxWidth: 320 }}
          />
          <Segmented
            value={statusFilter}
            onChange={(value) => setStatusFilter(String(value))}
            options={[
              { label: `全部 ${counts.all}`, value: 'all' },
              { label: `运行中 ${counts.running}`, value: 'running' },
              { label: `已完成 ${counts.completed}`, value: 'completed' },
              { label: `已取消 ${counts.cancelled}`, value: 'cancelled' },
              { label: `失败 ${counts.failed}`, value: 'failed' },
            ]}
          />
        </div>

        {visibleTasks.length === 0 && !loading ? (
          <EmptyState
            title={tasks.length === 0 ? '还没有任务记录' : '没有符合筛选条件的任务'}
            hint={tasks.length === 0 ? '先在「任务」页跑一个任务' : '试试清空搜索词或切换筛选条件'}
          />
        ) : (
          <Table<TaskSummary>
            rowKey="task_id"
            dataSource={visibleTasks}
            loading={loading}
            scroll={{ x: 'max-content' }}
            pagination={visibleTasks.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
            onRow={(record) => ({
              onClick: () => void openDetail(record.task_id),
              style: { cursor: 'pointer' },
            })}
            columns={[
              {
                title: '任务',
                dataIndex: 'query',
                key: 'query',
                ellipsis: true,
                render: (query: string) => (
                  <Tooltip title={query}>
                    <Text>{query}</Text>
                  </Tooltip>
                ),
              },
              {
                title: '状态',
                dataIndex: 'status',
                key: 'status',
                width: 100,
                render: (status: string) => <StatusTag status={status} />,
              },
              {
                title: '未通过章节',
                dataIndex: 'failed_chapters',
                key: 'failed_chapters',
                width: 120,
                render: (chapters: string[]) =>
                  chapters.length === 0 ? (
                    <Text type="secondary">—</Text>
                  ) : (
                    <Text type="warning">{chapters.join(', ')}</Text>
                  ),
              },
              {
                title: '耗时',
                key: 'duration',
                width: 100,
                render: (_, record) => (
                  <Text type="secondary">
                    {formatDuration(taskDurationSeconds(record.created_at, record.finished_at))}
                  </Text>
                ),
              },
              {
                title: '创建时间',
                dataIndex: 'created_at',
                key: 'created_at',
                width: 170,
                render: (value: string) => (
                  <Text type="secondary">{formatDateTime(value)}</Text>
                ),
              },
              {
                title: '操作',
                key: 'action',
                width: 80,
                render: (_, record) => (
                  <Button
                    type="link"
                    onClick={(event) => {
                      event.stopPropagation()
                      void openDetail(record.task_id)
                    }}
                  >
                    详情
                  </Button>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Drawer
        title={detail ? `任务详情 · ${detail.task_id.slice(0, 8)}` : '任务详情'}
        size="large"
        // 打开来源文档时临时隐藏抽屉（返回后自动恢复，上下文不丢）
        open={detail !== null && !hasDocument}
        loading={detailLoading}
        onClose={() => setDetail(null)}
        destroyOnHidden
      >
        {detail && (
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="任务">{detail.query}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Space size={6}>
                  <StatusTag status={detail.status} />
                  {detail.error_type && <Tag color="red">{detail.error_type}</Tag>}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="开始 / 结束">
                {formatDateTime(detail.created_at)} → {formatDateTime(detail.finished_at)}
              </Descriptions.Item>
              <Descriptions.Item label="耗时">
                {formatDuration(taskDurationSeconds(detail.created_at, detail.finished_at))}
              </Descriptions.Item>
              <Descriptions.Item label="重新规划次数">{detail.retry_count}</Descriptions.Item>
              <Descriptions.Item label="未通过校验章节">
                {detail.failed_chapters.length > 0 ? detail.failed_chapters.join(', ') : '无'}
              </Descriptions.Item>
            </Descriptions>

            <Card size="small" title="Agent Checkpoint 状态">
              {stateError ? (
                <Text type="secondary">{stateError}</Text>
              ) : state ? (
                <Row gutter={[16, 8]}>
                  <Col span={12}>
                    <Text type="secondary">当前步骤：</Text>
                    {state.current_step ?? '—'}
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">是否完成：</Text>
                    {state.is_complete ? '是' : '否'}
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">已写章节：</Text>
                    {state.chapters_written}
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">检索片段：</Text>
                    {state.sources_count}
                  </Col>
                </Row>
              ) : (
                <Text type="secondary">读取中…</Text>
              )}
            </Card>

            <Card size="small">
              <Tabs
                items={[
                  {
                    key: 'content',
                    label: '正文',
                    children: detail.final_answer ? (
                      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
                        <Space>
                          <Button
                            size="small"
                            icon={<CopyOutlined />}
                            onClick={() => void copyAnswer(detail.final_answer as string)}
                          >
                            复制
                          </Button>
                          <Button
                            size="small"
                            icon={<DownloadOutlined />}
                            onClick={() =>
                              downloadMarkdown(detail.final_answer as string, detail.query)
                            }
                          >
                            下载 .md
                          </Button>
                        </Space>
                        <MarkdownReader content={detail.final_answer} sources={detail.sources} />
                      </Space>
                    ) : (
                      <EmptyState compact title="该任务没有产出正文" hint="可能被取消或失败" />
                    ),
                  },
                  {
                    key: 'validation',
                    label: '校验',
                    children: detail.validation ? (
                      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
                        <div>
                          <Text strong>结论：</Text>
                          <Tag color={detail.validation.passed ? 'green' : 'red'}>
                            {detail.validation.passed ? '通过' : '未通过'}
                          </Tag>
                          <Text type="secondary">（{detail.validation.target}）</Text>
                        </div>
                        {detail.validation.issues.length > 0 ? (
                          <ul className="plain-list">
                            {detail.validation.issues.map((issue, index) => (
                              <li key={index}>
                                <Text type="warning">{issue}</Text>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <Text type="secondary">没有发现问题</Text>
                        )}
                      </Space>
                    ) : (
                      <EmptyState compact title="该任务没有校验记录" />
                    ),
                  },
                ]}
              />
            </Card>
          </Space>
        )}
      </Drawer>
    </PageContainer>
  )
}
