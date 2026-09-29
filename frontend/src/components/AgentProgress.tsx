import {
  CheckCircleFilled,
  ClockCircleOutlined,
  CloseCircleFilled,
  LoadingOutlined,
  MinusCircleOutlined,
  RedoOutlined,
} from '@ant-design/icons'
import { Collapse, Progress, Tag, Tooltip, Typography } from 'antd'
import type { ReactNode } from 'react'

const { Text } = Typography

export type StageStatus = 'wait' | 'process' | 'finish' | 'error'
export type ChapterValidation = 'pending' | 'passed' | 'failed'

/** 章节级进度：撰写与校验是一对循环，因此挂在同一个宏观阶段下 */
export interface ChapterView {
  index: number
  title: string
  /** 撰写次数（>1 表示被重写） */
  written: number
  writing: boolean
  validation: ChapterValidation
}

export interface MacroStage {
  key: string
  title: string
  status: StageStatus
  /** 阶段补充说明 */
  note?: string
  /** 右侧徽标 */
  badge?: ReactNode
  /** 阶段下的结构化小注（如重试/重新规划说明） */
  notes?: string[]
  /** 计划不需要检索时置灰跳过 */
  skipped?: boolean
  /** 进度条（大纲/章节阶段用） */
  progress?: { done: number; total: number }
  /** 仅「逐章撰写与校验」阶段使用 */
  chapters?: ChapterView[]
}

export interface LogEntry {
  id: number
  label: string
  message: string
  tone: 'info' | 'warn' | 'error'
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

function ChapterRow({ chapter }: { chapter: ChapterView }) {
  const writeTag = chapter.writing ? (
    <Tag color="processing">撰写中</Tag>
  ) : chapter.written > 0 ? (
    <Tag color="blue">已写{chapter.written > 1 ? ` ×${chapter.written}` : ''}</Tag>
  ) : (
    <Tag>待写</Tag>
  )

  const validateTag =
    chapter.validation === 'passed' ? (
      <Tag color="green">校验通过</Tag>
    ) : chapter.validation === 'failed' ? (
      <Tag color="red">校验未通过</Tag>
    ) : chapter.written > 0 ? (
      <Tag color="warning">待校验</Tag>
    ) : null

  return (
    <li className={`chapter-row${chapter.writing ? ' is-active' : ''}`}>
      <span className="chapter-index">第 {chapter.index} 章</span>
      <span className="chapter-title">{chapter.title || '（未命名）'}</span>
      <span className="chapter-tags">
        {writeTag}
        {validateTag}
      </span>
    </li>
  )
}

/**
 * Agent 执行进度。
 *
 * 按真实拓扑组织，而不是线性阶段列表：
 *   规划 → 检索 → 大纲 →「逐章撰写 ⇄ 校验」(章节级展开) → 整合
 * 校验失败会重写同一章、replan 会整轮回到规划，因此额外提供「轮次」与结构化执行日志。
 * 只展示结构化事件，不展示模型推理过程。
 */
export default function AgentProgress({
  stages,
  elapsedSeconds,
  running,
  hasStarted,
  round,
  log,
}: {
  stages: MacroStage[]
  elapsedSeconds: number
  running: boolean
  hasStarted: boolean
  round: number
  log: LogEntry[]
}) {
  const doneCount = stages.filter(
    (item) => item.status === 'finish' || item.skipped,
  ).length

  return (
    <div className="stage-list">
      <div className="stage-list-head">
        <Text type="secondary">
          {hasStarted ? `已完成 ${doneCount}/${stages.length} 个阶段` : '尚未运行'}
        </Text>
        <span>
          {round > 1 ? <Tag color="volcano">第 {round} 轮（重新规划后）</Tag> : null}
          {running && elapsedSeconds > 0 ? (
            <Text type="secondary">已用时 {elapsedSeconds}s</Text>
          ) : null}
        </span>
      </div>

      <ol className="stage-items">
        {stages.map((stage) => {
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
                  <StatusIcon status={stage.status} />
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

                {stage.chapters?.length ? (
                  <ul className="chapter-list">
                    {stage.chapters.map((chapter) => (
                      <ChapterRow key={chapter.index} chapter={chapter} />
                    ))}
                  </ul>
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

      {log.length > 0 ? (
        <Collapse
          className="event-log"
          ghost
          size="small"
          items={[
            {
              key: 'log',
              label: (
                <Text type="secondary">
                  <RedoOutlined /> 执行日志（结构化事件 {log.length} 条，不含推理过程）
                </Text>
              ),
              children: (
                <ul className="event-log-list">
                  {log.map((entry) => (
                    <li key={entry.id}>
                      <Tag className="event-log-tag">{entry.label}</Tag>
                      <Text
                        type={
                          entry.tone === 'error'
                            ? 'danger'
                            : entry.tone === 'warn'
                              ? 'warning'
                              : 'secondary'
                        }
                      >
                        {entry.message}
                      </Text>
                    </li>
                  ))}
                </ul>
              ),
            },
          ]}
        />
      ) : null}
    </div>
  )
}
