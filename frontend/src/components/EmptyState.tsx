import { Empty } from 'antd'
import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  hint?: ReactNode
  action?: ReactNode
  /** 用于抽屉 / 标签页等紧凑场景 */
  compact?: boolean
}

/** 统一的空状态：标题 + 引导说明 +（可选）操作按钮 */
export default function EmptyState({ title, hint, action, compact }: EmptyStateProps) {
  return (
    <div className={`empty-state${compact ? ' is-compact' : ''}`}>
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <div className="empty-state-text">
            <div className="empty-state-title">{title}</div>
            {hint ? <div className="empty-state-hint">{hint}</div> : null}
          </div>
        }
      >
        {action}
      </Empty>
    </div>
  )
}
