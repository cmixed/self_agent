import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

interface PageContainerProps {
  /**
   * 页面元信息保留在调用处，供后续统一读取；
   * 标题与说明已上移到顶栏，此处不再渲染（见 App.tsx PAGE_META）。
   */
  title: string
  eyebrow?: string
  description?: ReactNode
  /** 页头右侧操作区（渲染到顶栏右上角统一插槽） */
  extra?: ReactNode
  maxWidth?: number
  children: ReactNode
}

/**
 * 统一页面容器：内容区 + 顶栏操作区。
 * 板块标题 / 说明由顶栏统一展示；extra 按钮通过 portal 挂到顶栏右上角，
 * 避免各页面各自摆放、样式漂移。
 */
export default function PageContainer({
  extra,
  maxWidth = 1200,
  children,
}: PageContainerProps) {
  const [slot, setSlot] = useState<HTMLElement | null>(null)

  useEffect(() => {
    setSlot(document.querySelector<HTMLElement>('[data-page-actions-slot]'))
  }, [])

  const actions = extra ? <div className="app-header-page-actions__inner">{extra}</div> : null

  return (
    <div className="page-container" style={{ maxWidth }}>
      {actions
        ? slot
          ? createPortal(actions, slot)
          : <div className="page-header page-header--actions-only">{extra}</div>
        : null}
      <div className="page-body">{children}</div>
    </div>
  )
}
