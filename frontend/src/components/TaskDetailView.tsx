import {
  CopyOutlined,
  DownloadOutlined,
  ReloadOutlined,
  RightCircleOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Row,
  Space,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, getTask, getTaskState } from '../services/api'
import { useNav } from '../state/nav'
import { useTaskRun } from '../state/taskRun'
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

/** 失败后的下一步建议（按可读错误类型给出可执行动作）。 */
function failureHint(errorType: string | null | undefined): string | null {
  if (!errorType) return null
  const hints: Record<string, string> = {
    llm_quota_exhausted:
      '模型额度/余额不足：请为该 Provider 充值，或在顶栏切换到其它模型后点击「重新生成」。',
    llm_config_error:
      '模型密钥无效或缺失：修正 backend/.env 后**重启后端**（配置与 Provider 有进程内缓存），再点「继续生成」。',
    llm_rate_limited: '上游限流：稍等片刻后点击「继续生成」即可从断点续跑。',
    llm_timeout: '上游超时：点击「继续生成」会从断点继续，已完成的章节不会重跑。',
    llm_upstream_error: '上游服务异常：稍后点击「继续生成」重试。',
    graph_recursion_limit: '步骤超出安全上限：建议调整任务描述后「重新生成」。',
  }
  return hints[errorType] ?? null
}

/** 按任务状态给出「正文」空态文案：运行中不再误报「可能被取消或失败」。 */
function contentEmptyState(status: string | undefined) {
  if (status === 'running') {
    return <EmptyState compact title="任务正在执行中" hint="完成后正文会显示在这里（页面会自动刷新）" />
  }
  if (status === 'cancelled' || status === 'failed') {
    return <EmptyState compact title="该任务没有产出正文" hint="可能被取消或失败" />
  }
  return <EmptyState compact title="该任务没有产出正文" hint="任务已结束，但未生成正文内容" />
}

/** 按任务状态给出「校验」空态文案。 */
function validationEmptyState(status: string | undefined) {
  if (status === 'running') {
    return <EmptyState compact title="校验将在写作完成后进行" hint="页面会自动刷新" />
  }
  if (status === 'cancelled') {
    return <EmptyState compact title="任务已取消，没有校验记录" />
  }
  if (status === 'failed') {
    return <EmptyState compact title="任务失败，没有校验记录" />
  }
  return <EmptyState compact title="该任务没有校验记录" />
}

/** 任务详情视图：与「文档阅读」同一形态（内容区独立视图 + 统一返回）。 */
export default function TaskDetailView({ taskId }: { taskId: string }) {
  const { message } = App.useApp()
  const { back } = useViewStack()
  const { navigate } = useNav()
  const { running: taskRunning, resume, rerun } = useTaskRun()
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

  const running = detail?.status === 'running'
  const interrupted = detail?.status === 'failed' || detail?.status === 'cancelled'
  const hint = failureHint(detail?.error_type)
  const attempts = detail?.attempts ?? []

  // 运行中的任务静默轮询（不打 loading、失败忽略），结束后自动停止
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => {
      getTask(taskId)
        .then((data) => setDetail(data))
        .catch(() => {})
      getTaskState(taskId)
        .then((data) => setState(data))
        .catch(() => setState(null))
    }, 4000)
    return () => window.clearInterval(timer)
  }, [running, taskId])

  /** 继续生成 / 重新生成：关闭详情回到工作台，用既有进度界面消费 SSE。 */
  const handleResume = () => {
    closeAndRun(() => void resume(taskId))
  }

  const handleRerun = () => {
    if (!detail) return
    closeAndRun(() => void rerun(taskId, detail.query))
  }

  const closeAndRun = (start: () => void) => {
    back()
    navigate('workspace')
    start()
  }

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
          detail ? (
            <Space size={8}>
              {detail.final_answer ? (
                <Button
                  size="small"
                  icon={<DownloadOutlined />}
                  onClick={() => downloadMarkdown(detail.final_answer, detail.query)}
                >
                  下载 .md
                </Button>
              ) : null}
              {detail.resumable && !detail.running ? (
                <Tooltip title="从断点继续，已完成的章节不会重跑">
                  <Button
                    size="small"
                    type="primary"
                    icon={<RightCircleOutlined />}
                    disabled={taskRunning}
                    onClick={() => handleResume()}
                  >
                    继续生成
                  </Button>
                </Tooltip>
              ) : null}
              {!detail.running ? (
                <Tooltip title="用同一任务内容重新生成（新建一次运行，保留本次记录）">
                  <Button
                    size="small"
                    icon={<ReloadOutlined />}
                    disabled={taskRunning}
                    onClick={() => handleRerun()}
                  >
                    重新生成
                  </Button>
                </Tooltip>
              ) : null}
            </Space>
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

            {interrupted && hint ? (
              <Alert
                type="warning"
                showIcon
                message="任务被中断，可以继续生成"
                description={hint}
              />
            ) : null}

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

            {attempts.length > 1 ? (
              <Card size="small" title={`执行历史（${attempts.length} 次）`}>
                <div className="entity-list">
                  {attempts.map((attempt) => (
                    <div className="entity-item" key={attempt.attempt_no}>
                      <div className="entity-item__main">
                        <Space size={8}>
                          <Text strong>第 {attempt.attempt_no} 次</Text>
                          <StatusTag status={attempt.status} />
                          {attempt.error_type ? <Tag color="red">{attempt.error_type}</Tag> : null}
                        </Space>
                        <Text type="secondary" className="entity-item__meta">
                          {formatDateTime(attempt.started_at)} →{' '}
                          {attempt.finished_at ? formatDateTime(attempt.finished_at) : '进行中'}
                          {attempt.retry_count > 0 ? ` · 重新规划 ${attempt.retry_count} 次` : ''}
                        </Text>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            ) : null}

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
                      contentEmptyState(detail.status)
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
                      validationEmptyState(detail.status)
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
