import { Space, Typography } from 'antd'
import type { ReactNode } from 'react'

const { Title, Text } = Typography

interface PageContainerProps {
  title: string
  /** 区域小标题（工作台 / 知识库 …） */
  eyebrow?: string
  description?: ReactNode
  /** 页头右侧操作区 */
  extra?: ReactNode
  maxWidth?: number
  children: ReactNode
}

/**
 * 统一页面容器：页头（区域 + 标题 + 说明 + 操作）+ 内容区垂直间距。
 */
export default function PageContainer({
  title,
  eyebrow,
  description,
  extra,
  maxWidth = 1200,
  children,
}: PageContainerProps) {
  return (
    <div className="page-container" style={{ maxWidth }}>
      <div className="page-header">
        <div className="page-header-text">
          {eyebrow ? <span className="page-eyebrow">{eyebrow}</span> : null}
          <Title level={4} className="page-title">
            {title}
          </Title>
          {description ? (
            <Text type="secondary" className="page-description">
              {description}
            </Text>
          ) : null}
        </div>
        {extra ? <Space size="small">{extra}</Space> : null}
      </div>
      <div className="page-body">{children}</div>
    </div>
  )
}
