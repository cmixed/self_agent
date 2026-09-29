import {
  CheckCircleFilled,
  ClockCircleOutlined,
  CloseCircleFilled,
  LoadingOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons'
import { Progress, Tooltip, Typography } from 'antd'
import type { ReactNode } from 'react'

const { Text } = Typography

export type StageStatus = 'wait' | 'process' | 'finish' | 'error'

export interface StageView {
  key: string
  title: string
  status: StageStatus
  /** 阶段内的补充说明，如「已写 2/5 章」 */
  note?: string
  /** 右侧徽标 */
  badge?: ReactNode
  /** 该阶段下的结构化小注（如重试说明） */
  notes?: string[]
  /** 章节进度条（仅撰写阶段用） */
  progress?: { done: number; total: number }
  /** 计划不需要检索时置灰跳过 */
  skipped?: boolean
}

function StatusIcon({ status }: { status: StageStatus }) {
  switch (status) {
    case 'finish':
      return <CheckCircleFilled className="stage-icon stage-icon--finish" />
    case 'process':
      return <LoadingOutlined className="stage-icon stage-icon--process" />
    case 'error':
      return <CloseCircleFilled className="stage-icon stage-icon--error" />
    default:
      return <ClockCircleOutlined className="stage-icon stage-icon--wait" />
  }
}

/**
 * Agent 执行进度列表。
 *
 * 只展示结构化阶段与事件消息，不展示模型推理过程。
 * 不用 antd Steps：其 current 与 items[].status 的优先级不可靠，
 * 会把未开始的首项渲染成「进行中」。
 */
export default function AgentProgress({
  stages,
  elapsedSeconds,
  running,
  hasStarted,
}: {
  stages: StageView[]
  elapsedSeconds: number
  running: boolean
  hasStarted: boolean
}) {
  const doneCount = stages.filter((item) => item.status === 'finish' || item.skipped).length

  return (
    <div className="stage-list">
      <div className="stage-list-head">
        <Text type="secondary">
          {hasStarted ? `已完成 ${doneCount}/${stages.length} 个阶段` : '尚未运行'}
        </Text>
        {running && elapsedSeconds > 0 ? (
          <Text type="secondary">已用时 {elapsedSeconds}s</Text>
        ) : null}
      </div>

      <ol className="stage-items">
        {stages.map((stage) => {
          const status: StageStatus = stage.skipped ? 'wait' : stage.status
          const isCurrent = !stage.skipped && stage.status === 'process'
          return (
            <li
              key={stage.key}
              className={`stage-item${isCurrent ? ' is-current' : ''}${
                stage.skipped ? ' is-skipped' : ''
              }`}
            >
              <span className="stage-marker">
                {stage.skipped ? (
                  <Tooltip title="计划不需要知识库检索，已跳过">
                    <MinusCircleOutlined className="stage-icon stage-icon--skip" />
                  </Tooltip>
                ) : (
                  <StatusIcon status={status} />
                )}
              </span>

              <div className="stage-body">
                <div className="stage-row">
                  <Text strong={isCurrent} type={stage.skipped ? 'secondary' : undefined}>
                    {stage.title}
                  </Text>
                  {stage.note ? <Text type="secondary">{stage.note}</Text> : null}
                  <span className="stage-badge">{stage.badge}</span>
                </div>

                {stage.progress && stage.progress.total > 0 ? (
                  <Progress
                    className="stage-progress"
                    percent={Math.round((stage.progress.done / stage.progress.total) * 100)}
                    size="small"
                    showInfo={false}
                    status={stage.status === 'error' ? 'exception' : 'normal'}
                  />
                ) : null}

                {stage.notes?.length ? (
                  <ul className="stage-notes">
                    {stage.notes.map((note, index) => (
                      <li key={`${stage.key}-${index}`}>
                        <Text type="warning">{note}</Text>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
