import { CopyOutlined, DownloadOutlined } from '@ant-design/icons'
import { App, Button, Card, Col, Descriptions, Empty, Row, Space, Tabs, Tag, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, getTask, getTaskState } from '../services/api'
import type { TaskDetail, TaskState } from '../types/api'
import { downloadMarkdown } from '../utils/download'
import { formatDateTime, formatDuration, taskDurationSeconds } from '../utils/format'
import EmptyState from './EmptyState'
import ErrorNotice from './ErrorNotice'
import MarkdownReader from './MarkdownReader'
import StatusTag from './StatusTag'
import ViewHeader from './ViewHeader'
import { useViewStack } from './ViewStack'

const { Text } = Typography

/** 任务详情视图：与「文档阅读」同一形态（内容区独立视图 + 统一返回）。 */
export default function TaskDetailView({ taskId }: { taskId: string }) {
  const { message } = App.useApp()
  const { back } = useViewStack()
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState<TaskState | null>(null)
  const [stateError, setStateError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    setState(null)
    setStateError(null)
    getTask(taskId)
      .then((data) => setDetail(data))
      .catch((err) => setError(err instanceof ApiError ? err.message : '加载任务详情失败'))
      .finally(() => setLoading(false))
    // 自动读取 Agent checkpoint 状态（失败时给出可读提示，不影响详情）
    getTaskState(taskId)
      .then((data) => setState(data))
      .catch((err) =>
        setStateError(
          err instanceof ApiError
            ? err.status === 503
              ? '后端未启用 Checkpoint'
              : '该任务没有可读取的 Checkpoint 记录'
            : '读取 Checkpoint 失败',
        ),
      )
  }, [taskId])

  useEffect(() => {
    load()
  }, [load])

  const copyAnswer = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content)
      message.success('已复制到剪贴板')
    } catch {
      setError('复制失败（浏览器未授权剪贴板），请手动选择文本复制')
    }
  }

  return (
    <div className="view-panel">
      <ViewHeader
        title={`任务详情 · ${taskId.slice(0, 8)}`}
        subtitle={detail ? <StatusTag status={detail.status} /> : null}
        onBack={back}
        extra={
          detail?.final_answer ? (
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => downloadMarkdown(detail.final_answer, detail.query)}
            >
              下载 .md
            </Button>
          ) : null
        }
      />
      <div className="view-body">
        {loading && !detail ? (
          <Empty description="加载中…" />
        ) : error && !detail ? (
          <ErrorNotice message={error} onRetry={load} />
        ) : detail ? (
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            {error ? <ErrorNotice message={error} onClose={() => setError(null)} /> : null}

            <Descriptions column={{ xs: 1, sm: 1, md: 2 }} size="small" bordered>
              <Descriptions.Item label="任务" span={2}>
                {detail.query}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Space size={6}>
                  <StatusTag status={detail.status} />
                  {detail.error_type ? <Tag color="red">{detail.error_type}</Tag> : null}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="耗时">
                {formatDuration(taskDurationSeconds(detail.created_at, detail.finished_at))}
              </Descriptions.Item>
              <Descriptions.Item label="开始" span={1}>
                {formatDateTime(detail.created_at)}
              </Descriptions.Item>
              <Descriptions.Item label="结束" span={1}>
                {formatDateTime(detail.finished_at)}
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
                            onClick={() => void copyAnswer(detail.final_answer)}
                          >
                            复制
                          </Button>
                          <Button
                            size="small"
                            icon={<DownloadOutlined />}
                            onClick={() => downloadMarkdown(detail.final_answer, detail.query)}
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
        ) : null}
      </div>
    </div>
  )
}
