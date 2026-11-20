import type { ReactNode } from 'react'
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

interface PageSearchValue {
  /** 当前页面是否注册了页内搜索 */
  hasSearch: boolean
  /** 页面挂载搜索框时注册聚焦动作；返回清理函数 */
  register: (focus: () => void) => () => void
  /** 聚焦当前页面的搜索框；没有注册时不做任何事 */
  trigger: () => void
}

const PageSearchContext = createContext<PageSearchValue | null>(null)

/**
 * 页内搜索总线：页面把「聚焦自己的搜索框」注册进来，
 * dock 的搜索按钮与 `/` 快捷键统一调用 `trigger`（§17 导航分层）。
 *
 * 同一时刻只有一个页面挂载，因此只保留一个处理函数；旧页面的清理
 * 不会误清掉新页面刚注册的处理函数（按引用比较）。
 */
export function PageSearchProvider({ children }: { children: ReactNode }) {
  const handlerRef = useRef<(() => void) | null>(null)
  const [hasSearch, setHasSearch] = useState(false)

  const register = useCallback((focus: () => void) => {
    handlerRef.current = focus
    setHasSearch(true)
    return () => {
      if (handlerRef.current === focus) {
        handlerRef.current = null
        setHasSearch(false)
      }
    }
  }, [])

  const trigger = useCallback(() => {
    handlerRef.current?.()
  }, [])

  return (
    <PageSearchContext.Provider value={{ hasSearch, register, trigger }}>
      {children}
    </PageSearchContext.Provider>
  )
}

export function usePageSearch(): PageSearchValue {
  const context = useContext(PageSearchContext)
  if (context === null) {
    throw new Error('usePageSearch 必须在 PageSearchProvider 内部使用')
  }
  return context
}

interface PageSearchFieldProps {
  children: ReactNode
  className?: string
}

/**
 * 页内搜索框容器：挂载时把「聚焦输入框」注册到总线，
 * 卸载时自动注销（例如知识库从文件视图切到共享关系图）。
 */
export function PageSearchField({ children, className = 'page-search' }: PageSearchFieldProps) {
  const { register } = usePageSearch()
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(
    () =>
      register(() => {
        const input = containerRef.current?.querySelector<HTMLInputElement>('input')
        if (!input) return
        input.focus()
        input.select()
      }),
    [register],
  )

  return (
    <div ref={containerRef} className={className}>
      {children}
    </div>
  )
}
