import { CloseOutlined, DownOutlined, StopOutlined } from '@ant-design/icons'
import { App, Badge, Button, Dropdown, Popconfirm, Tooltip } from 'antd'
import { useEffect, useState } from 'react'

import { useIsNarrow } from '../hooks/useIsNarrow'
import { useNav } from '../state/nav'
import { useTaskRun } from '../state/taskRun'
import type { TaskSummary } from '../types/api'
import { formatDuration } from '../utils/format'
import {
  elapsedSeconds,
  modeLabel,
  runningTaskStage,
  runningTaskTitle,
  sliceRunningTasks,
} from '../utils/runningTasks'
import { useViewStack } from './ViewStack'

/** 每秒刷新一次「已运行时长」（没有任务时不启动定时器）。 */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  return now
}

function tipContent(task: TaskSummary, now: number) {
  const mode = modeLabel(task.mode)
  return (
    <div className="run-pill__tip">
      <div className="run-pill__tip-query">{task.query}</div>
      <div className="run-pill__tip-row">阶段：{runningTaskStage(task)}</div>
      {mode ? <div className="run-pill__tip-row">模式：{mode}</div> : null}
      <div className="run-pill__tip-row">
        已运行：{formatDuration(elapsedSeconds(task.created_at, now))}
      </div>
      <div className="run-pill__tip-hint">点击在工作台查看实时进度 · 右侧按钮终止</div>
    </div>
  )
}

interface CapsuleProps {
  task: TaskSummary
  now: number
  active: boolean
  onOpen: (taskId: string) => void
  onCancel: (taskId: string) => void
}

/** 单个运行中任务胶囊：脉冲点 + 标题 + 已运行时长 + 终止按钮。 */
function Capsule({ task, now, active, onOpen, onCancel }: CapsuleProps) {
  return (
    <div className={`run-pill${active ? ' is-active' : ''}`}>
      <Tooltip title={tipContent(task, now)} placement="bottomRight">
        <button
          type="button"
          className="run-pill__main"
          aria-label={`查看任务：${task.query}`}
          onClick={() => onOpen(task.task_id)}
        >
          <Badge status="processing" />
          <span className="run-pill__title">{runningTaskTitle(task.query)}</span>
          <span className="run-pill__meta">
            {formatDuration(elapsedSeconds(task.created_at, now))}
          </span>
        </button>
      </Tooltip>
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
    </div>
  )
}

/**
 * 顶栏「运行中任务」胶囊（AGENTS.md §17/§19）。
 *
 * 任务执行归属后端，胶囊只是观察入口：点击切换工作台观察对象（不取消任务），
 * 终止按钮会真正请求后端取消。支持同时多个任务。
 */
export default function RunningTasks() {
  const { runningTasks, taskId, selectTask, cancelRunning } = useTaskRun()
  const { navigate } = useNav()
  const { closeAll } = useViewStack()
  const { message } = App.useApp()
  const narrow = useIsNarrow()
  const now = useNow(runningTasks.length > 0)

  if (runningTasks.length === 0) return null

  const openTask = (targetId: string) => {
    closeAll()
    navigate('workspace')
    // 当前已观察的就是它：只切回工作台，不重建订阅（避免白清一次进度）
    if (targetId !== taskId) void selectTask(targetId)
  }

  const cancel = (targetId: string) => {
    void cancelRunning(targetId).then(() => message.success('已请求终止任务'))
  }

  const menuItems = runningTasks.map((task) => ({
    key: task.task_id,
    label: (
      <div className="run-pill-menu">
        <div className="run-pill-menu__body">
          <span className="run-pill-menu__title">{runningTaskTitle(task.query, 24)}</span>
          <span className="run-pill-menu__stage">
            {runningTaskStage(task)} · {formatDuration(elapsedSeconds(task.created_at, now))}
          </span>
        </div>
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
      </div>
    ),
  }))

  // 窄屏：折叠成一个「N 个任务执行中」入口，避免顶栏被胶囊挤满
  if (narrow) {
    return (
      <Dropdown
        trigger={['click']}
        menu={{ items: menuItems, onClick: ({ key }) => openTask(key) }}
      >
        <Button size="small" type="text" className="run-pills__more" aria-label="运行中的任务">
          <Badge status="processing" />
          <span>{runningTasks.length} 个任务执行中</span>
          <DownOutlined />
        </Button>
      </Dropdown>
    )
  }

  const { visible, overflow } = sliceRunningTasks(runningTasks, {
    activeTaskId: taskId,
  })
  const overflowItems = menuItems.filter((item) =>
    overflow.some((task) => task.task_id === item.key),
  )

  return (
    <div className="run-pills" aria-label="运行中的任务">
      {visible.map((task) => (
        <Capsule
          key={task.task_id}
          task={task}
          now={now}
          active={task.task_id === taskId}
          onOpen={openTask}
          onCancel={cancel}
        />
      ))}
      {overflow.length > 0 ? (
        <Dropdown
          trigger={['click']}
          menu={{ items: overflowItems, onClick: ({ key }) => openTask(key) }}
        >
          <Button size="small" type="text" className="run-pills__more" aria-label="更多运行中任务">
            +{overflow.length}
            <DownOutlined />
          </Button>
        </Dropdown>
      ) : null}
    </div>
  )
}
