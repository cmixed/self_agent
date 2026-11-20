import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

interface PageTabbarProps {
  /** 当前页 key，用于给 dock 里的槽打标记。 */
  page: string
  /** tab 按钮 + 右端状态胶囊。 */
  children: ReactNode
}

/**
 * 页面分区标签栏：渲染到 dock 的 [data-page-tabbar-slot] 槽，
 * 让成员 / 设置这类有多分区的页面在底部胶囊条里切换，页面本体只留内容。
 * dock 未就绪时降级为页面内横条（如登录态切换瞬间）。
 */
export default function PageTabbar({ page, children }: PageTabbarProps) {
  const [slot, setSlot] = useState<HTMLElement | null>(null)

  useEffect(() => {
    setSlot(document.querySelector<HTMLElement>('[data-page-tabbar-slot]'))
  }, [])

  const content = (
    <div className="tabbar tabbar--docked" role="tablist" aria-label={`${page} 分区`}>
      {children}
    </div>
  )

  return slot ? createPortal(content, slot) : content
}
