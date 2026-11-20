import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

interface PageSearchProps {
  /** 页面搜索框（Input 等），portal 到顶栏导航的 [data-page-search-slot] 槽 */
  children: ReactNode
}

/**
 * 页面级搜索框槽：把当前页的搜索输入送到顶部导航栏，
 * dock 的「搜索」按钮与 `/` 快捷键会聚焦它（见 App.openSearch）。
 * 槽未就绪时降级渲染在页面内。
 */
export default function PageSearch({ children }: PageSearchProps) {
  const [slot, setSlot] = useState<HTMLElement | null>(null)

  useEffect(() => {
    setSlot(document.querySelector<HTMLElement>('[data-page-search-slot]'))
  }, [])

  return slot ? (
    createPortal(<div className="app-header-search__inner">{children}</div>, slot)
  ) : (
    <div className="page-search">{children}</div>
  )
}
