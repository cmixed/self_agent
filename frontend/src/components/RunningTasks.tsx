import { CloseOutlined, DownOutlined, StopOutlined } from '@ant-design/icons'
import { App, Badge, Button, Dropdown, Popconfirm, Tooltip } from 'antd'
import { useEffect, useMemo, useState } from 'react'

import { useIsNarrow } from '../hooks/useIsNarrow'
import { useNav } from '../state/nav'
import { useTaskRun } from '../state/taskRun'
import type { TaskSummary } from '../types/api'
import { formatDateTime, formatDuration, taskDurationSeconds } from '../utils/format'
import {
  elapsedSeconds,
  mergeTaskPills,
  modeLabel,
  pillStatusLabel,
  runningTaskStage,
  runningTaskTitle,
  sliceRunningTasks,
  taskPillState,
} from '../utils/runningTasks'
import type { TaskPillState } from '../utils/runningTasks'
import { useViewStack } from './ViewStack'

/** 每秒刷新一次「已运行时长」（没有运行中任务时不启动定时器）。 */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  return now
}

const BADGE_STATUS = {
  running: 'processing',
  completed: 'success',
  failed: 'error',
  cancelled: 'default',
} as const

function tipContent(task: TaskSummary, state: TaskPillState, now: number) {
  const mode = modeLabel(task.mode)
  const terminal = state !== 'running'
  const duration = formatDuration(taskDurationSeconds(task.created_at, task.finished_at))
  return (
    <div className="run-pill__tip">
      <div className="run-pill__tip-query">{task.query}</div>
      <div className="run-pill__tip-row">
        状态：{pillStatusLabel(state)}
        {terminal && duration !== '—' ? ` · 用时 ${duration}` : ''}
      </div>
      {terminal ? null : <div className="run-pill__tip-row">阶段：{runningTaskStage(task)}</div>}
      {state === 'failed' && task.error_type ? (
        <div className="run-pill__tip-row">失败原因：{task.error_type}</div>
      ) : null}
      {mode ? <div className="run-pill__tip-row">模式：{mode}</div> : null}
      {terminal ? (
        task.finished_at ? (
          <div className="run-pill__tip-row">结束：{formatDateTime(task.finished_at)}</div>
        ) : null
      ) : (
        <div className="run-pill__tip-row">
          已运行：{formatDuration(elapsedSeconds(task.created_at, now))}
        </div>
      )}
      <div className="run-pill__tip-hint">
        {terminal
          ? '点击在工作台查看结果 · 右侧 × 关闭提醒'
          : '点击在工作台查看实时进度 · 右侧按钮终止'}
      </div>
    </div>
  )
}

interface CapsuleProps {
  task: TaskSummary
  now: number
  active: boolean
  onOpen: (taskId: string) => void
  onCancel: (taskId: string) => void
  onDismiss: (taskId: string) => void
}

/** 单个任务胶囊：运行中显示脉冲点与终止按钮；完成后常驻显示结果状态与关闭按钮。 */
function Capsule({ task, now, active, onOpen, onCancel, onDismiss }: CapsuleProps) {
  const state = taskPillState(task)
  const terminal = state !== 'running'
  return (
    <div className={`run-pill is-${state}${active ? ' is-active' : ''}`}>
      <Tooltip title={tipContent(task, state, now)} placement="bottomRight">
        <button
          type="button"
          className="run-pill__main"
          aria-label={`${terminal ? '查看已完成任务' : '查看任务'}：${task.query}`}
          onClick={() => onOpen(task.task_id)}
        >
          <Badge status={BADGE_STATUS[state]} />
          <span className="run-pill__title">{runningTaskTitle(task.query)}</span>
          <span className="run-pill__meta">
            {terminal
              ? pillStatusLabel(state)
              : formatDuration(elapsedSeconds(task.created_at, now))}
          </span>
        </button>
      </Tooltip>
      {terminal ? (
        <Tooltip title="关闭提醒">
          <Button
            type="text"
            size="small"
            className="run-pill__stop"
            aria-label={`关闭任务提醒：${task.query}`}
            icon={<CloseOutlined />}
            onClick={() => onDismiss(task.task_id)}
          />
        </Tooltip>
      ) : (
        <Popconfirm
          title="终止这个任务？"
          description="已生成的章节会保留，可在任务历史里查看。"
          okText="终止"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          onConfirm={() => onCancel(task.task_id)}
        >
          <Button
            type="text"
            size="small"
            danger
            className="run-pill__stop"
            aria-label={`终止任务：${task.query}`}
            icon={<StopOutlined />}
          />
        </Popconfirm>
      )}
    </div>
  )
}

/**
 * 顶栏任务胶囊（AGENTS.md §17/§19）。
 *
 * - 运行中：点击切换工作台观察对象（不取消任务），右侧按钮终止；
 * - 已完成/失败/已终止：常驻等用户查看，点击打开结果，× 或查看后消失。
 *
 * 任务执行归属后端，顶栏只是观察与管理入口，支持同时多个任务。
 */
export default function RunningTasks() {
  const { runningTasks, finishedTasks, taskId, selectTask, cancelRunning, ackFinished } =
    useTaskRun()
  const { navigate } = useNav()
  const { closeAll } = useViewStack()
  const { message } = App.useApp()
  const narrow = useIsNarrow()
  const tasks = useMemo(
    () => mergeTaskPills(runningTasks, finishedTasks),
    [runningTasks, finishedTasks],
  )
  const now = useNow(runningTasks.length > 0)

  if (tasks.length === 0) return null

  const openTask = (targetId: string) => {
    closeAll()
    navigate('workspace')
    const target = tasks.find((task) => task.task_id === targetId)
    if (targetId !== taskId) {
      void selectTask(targetId)
      return
    }
    // 当前观察的就是它：只切回工作台；已结束的顺便清掉常驻胶囊
    if (target && taskPillState(target) !== 'running') ackFinished(targetId)
  }

  const cancel = (targetId: string) => {
    void cancelRunning(targetId).then(() => message.success('已请求终止任务'))
  }

  const dismiss = (targetId: string) => {
    ackFinished(targetId)
  }

  const statusLine = (task: TaskSummary) => {
    const state = taskPillState(task)
    if (state === 'running') {
      return `${runningTaskStage(task)} · ${formatDuration(elapsedSeconds(task.created_at, now))}`
    }
    const duration = formatDuration(taskDurationSeconds(task.created_at, task.finished_at))
    return `${pillStatusLabel(state)}${duration === '—' ? '' : ` · 用时 ${duration}`}`
  }

  const menuItems = tasks.map((task) => {
    const terminal = taskPillState(task) !== 'running'
    return {
      key: task.task_id,
      label: (
        <div className="run-pill-menu">
          <div className="run-pill-menu__body">
            <span className="run-pill-menu__title">{runningTaskTitle(task.query, 24)}</span>
            <span className="run-pill-menu__stage">{statusLine(task)}</span>
          </div>
          {terminal ? (
            <Button
              type="text"
              size="small"
              aria-label={`关闭任务提醒：${task.query}`}
              icon={<CloseOutlined />}
              onClick={(event) => {
                event.stopPropagation()
                dismiss(task.task_id)
              }}
            />
          ) : (
            <Button
              type="text"
              size="small"
              danger
              aria-label={`终止任务：${task.query}`}
              icon={<CloseOutlined />}
              onClick={(event) => {
                event.stopPropagation()
                cancel(task.task_id)
              }}
            />
          )}
        </div>
      ),
    }
  })

  const runningCount = runningTasks.length
  const finishedCount = finishedTasks.length
  const badgeStatus =
    runningCount > 0
      ? 'processing'
      : finishedTasks.some((task) => task.status === 'failed')
        ? 'error'
        : 'success'
  const summary = [
    runningCount > 0 ? `${runningCount} 个执行中` : '',
    finishedCount > 0 ? `${finishedCount} 个待查看` : '',
  ]
    .filter(Boolean)
    .join(' · ')

  // 窄屏：折叠成一个入口，避免顶栏被胶囊挤满
  if (narrow) {
    return (
      <Dropdown
        trigger={['click']}
        menu={{ items: menuItems, onClick: ({ key }) => openTask(key) }}
      >
        <Button size="small" type="text" className="run-pills__more" aria-label="任务状态">
          <Badge status={badgeStatus} />
          <span>{summary}</span>
          <DownOutlined />
        </Button>
      </Dropdown>
    )
  }

  const { visible, overflow } = sliceRunningTasks(tasks, {
    activeTaskId: taskId,
  })
  const overflowItems = menuItems.filter((item) =>
    overflow.some((task) => task.task_id === item.key),
  )

  return (
    <div className="run-pills" aria-label="任务胶囊">
      {visible.map((task) => (
        <Capsule
          key={task.task_id}
          task={task}
          now={now}
          active={task.task_id === taskId}
          onOpen={openTask}
          onCancel={cancel}
          onDismiss={dismiss}
        />
      ))}
      {overflow.length > 0 ? (
        <Dropdown
          trigger={['click']}
          menu={{ items: overflowItems, onClick: ({ key }) => openTask(key) }}
        >
          <Button size="small" type="text" className="run-pills__more" aria-label="更多任务">
            +{overflow.length}
            <DownOutlined />
          </Button>
        </Dropdown>
      ) : null}
    </div>
  )
}
