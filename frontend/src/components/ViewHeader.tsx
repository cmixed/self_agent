import { ArrowLeftOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import type { ReactNode } from 'react'

/**
 * 统一的视图头：左侧「← 返回」+ 标题（+ 副标题），右侧操作区。
 * 「文档阅读」与「任务详情」共用，保证观感与交互一致。
 */
export default function ViewHeader({
  title,
  subtitle,
  onBack,
  extra,
}: {
  title: ReactNode
  subtitle?: ReactNode
  onBack: () => void
  extra?: ReactNode
}) {
  return (
    <div className="view-header">
      <div className="view-header__left">
        <Button
          size="small"
          type="text"
          className="view-header__back"
          icon={<ArrowLeftOutlined />}
          onClick={onBack}
        >
          返回
        </Button>
        <span className="view-header__divider" aria-hidden="true" />
        <div className="view-header__text">
          <span className="view-header__title">{title}</span>
          {subtitle ? <span className="view-header__subtitle">{subtitle}</span> : null}
        </div>
      </div>
      {extra ? <div className="view-header__extra">{extra}</div> : null}
    </div>
  )
}
