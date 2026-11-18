import type { ReactNode } from 'react'

interface PageContainerProps {
  /**
   * 页面元信息保留在调用处，供后续统一读取；
   * 标题与说明已上移到顶栏，此处不再渲染（见 App.tsx PAGE_META）。
   */
  title: string
  eyebrow?: string
  description?: ReactNode
  /** 页头右侧操作区 */
  extra?: ReactNode
  maxWidth?: number
  children: ReactNode
}

/**
 * 统一页面容器：只保留操作区与内容区。
 * 板块标题 / 说明由顶栏统一展示，避免同屏重复。
 */
export default function PageContainer({
  extra,
  maxWidth = 1200,
  children,
}: PageContainerProps) {
  return (
    <div className="page-container" style={{ maxWidth }}>
      {extra ? <div className="page-header page-header--actions-only">{extra}</div> : null}
      <div className="page-body">{children}</div>
    </div>
  )
}
