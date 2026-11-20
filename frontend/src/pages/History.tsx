import { Button, Card, Segmented, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'

import EmptyState from '../components/EmptyState'
import { usePageRefresh } from '../hooks/usePageRefresh'
import ErrorNotice from '../components/ErrorNotice'
import PageContainer from '../components/PageContainer'
import { usePageSearch, usePageSearchRegistration } from '../components/PageSearch'
import PageTabs from '../components/PageTabs'
import StatusTag from '../components/StatusTag'
import { useViewStack } from '../components/ViewStack'
import { ApiError, listTasks } from '../services/api'
import { useTaskRun } from '../state/taskRun'
import type { OutputMode, TaskSummary } from '../types/api'
import { formatDateTime, formatDuration, taskDurationSeconds } from '../utils/format'

const { Text } = Typography

const PAGE_EYEBROW = '任务历史'
const PAGE_TITLE = '查看过去任务的执行状态与结果'
const PAGE_DESCRIPTION = '支持按状态筛选；点击任务可查看正文、来源与校验结论。'
const PAGE_MAX_WIDTH = 1200

export default function HistoryPage() {
  const { openTask } = useViewStack()
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { keyword } = usePageSearch()
  const [statusFilter, setStatusFilter] = useState('all')
  const [outputMode, setOutputMode] = useState<OutputMode>('generate')

  usePageSearchRegistration('搜索任务内容')

  const { tasksVersion } = useTaskRun()

  const refresh = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) setLoading(true)
      setError(null)
      try {
        const data = await listTasks(100, undefined, outputMode)
        setTasks(data.tasks)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : '加载任务历史失败')
      } finally {
        if (!options?.silent) setLoading(false)
      }
    },
    [outputMode],
  )

  useEffect(() => {
    void refresh()
  }, [refresh])

  usePageRefresh(refresh)

  // 任务开始 / 结束（tasksVersion 变化）时静默刷新，无需手动点刷新
  const versioned = useRef(false)
  useEffect(() => {
    if (!versioned.current) {
      versioned.current = true
      return
    }
    void refresh({ silent: true })
  }, [refresh, tasksVersion])

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
        <Space>
          <Segmented
            value={outputMode}
            onChange={(value) => {
              setOutputMode(value as OutputMode)
              setStatusFilter('all')
            }}
            options={[
              { label: '生成内容', value: 'generate' },
              { label: '原文输出', value: 'verbatim' },
            ]}
          />
        </Space>
      }
    >
      {error && (
        <ErrorNotice
          message={error}
          onClose={() => setError(null)}
          onRetry={() => void refresh()}
        />
      )}

      {/* 状态筛选是页面分区标签，统一放在内容区顶部（§17 导航分层） */}
      <PageTabs
        label="任务状态"
        activeKey={statusFilter}
        onChange={setStatusFilter}
        items={[
          {
            key: 'all',
            label: (
              <>
                全部 <b>{counts.all}</b>
              </>
            ),
          },
          {
            key: 'running',
            label: (
              <>
                运行中 <b>{counts.running}</b>
              </>
            ),
          },
          {
            key: 'completed',
            label: (
              <>
                已完成 <b>{counts.completed}</b>
              </>
            ),
          },
          {
            key: 'cancelled',
            label: (
              <>
                已取消 <b>{counts.cancelled}</b>
              </>
            ),
          },
          {
            key: 'failed',
            label: (
              <>
                失败 <b>{counts.failed}</b>
              </>
            ),
          },
        ]}
      />

      <Card>
        {visibleTasks.length === 0 && !loading ? (
          <EmptyState
            title={
              tasks.length === 0
                ? outputMode === 'verbatim'
                  ? '还没有原文输出记录'
                  : '还没有任务记录'
                : '没有符合筛选条件的任务'
            }
            hint={tasks.length === 0 ? '先在「工作台」跑一个任务' : '试试清空搜索词或切换筛选条件'}
          />
        ) : (
          <Table<TaskSummary>
            rowKey="task_id"
            dataSource={visibleTasks}
            loading={loading}
            scroll={{ x: 'max-content' }}
            pagination={visibleTasks.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
            onRow={(record) => ({
              onClick: () => openTask(record.task_id),
              style: { cursor: 'pointer' },
            })}
            columns={[
              {
                title: '任务',
                dataIndex: 'query',
                key: 'query',
                ellipsis: true,
                render: (query: string, record: TaskSummary) => (
                  <Space size={6}>
                    {record.output_mode === 'verbatim' ? <Tag color="cyan">原文</Tag> : null}
                    <Tooltip title={query}>
                      <Text>{query}</Text>
                    </Tooltip>
                  </Space>
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
                render: (value: string) => <Text type="secondary">{formatDateTime(value)}</Text>,
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
                      openTask(record.task_id)
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
    </PageContainer>
  )
}
