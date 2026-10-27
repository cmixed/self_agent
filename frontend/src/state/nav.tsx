import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

export const PAGES = [
  'workspace',
  'knowledge',
  'skills',
  'presets',
  'providers',
  'history',
  'memory',
  'settings',
] as const
export type PageKey = (typeof PAGES)[number]

interface NavValue {
  page: PageKey
  navigate: (page: PageKey) => void
}

const NavContext = createContext<NavValue | null>(null)

/** 页面导航（当前为轻量本地状态，不引入路由依赖）。 */
export function NavProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<PageKey>('workspace')
  const navigate = useCallback((next: PageKey) => setPage(next), [])
  const value = useMemo<NavValue>(() => ({ page, navigate }), [page, navigate])
  return <NavContext.Provider value={value}>{children}</NavContext.Provider>
}

export function useNav(): NavValue {
  const context = useContext(NavContext)
  if (context === null) {
    throw new Error('useNav 必须在 NavProvider 内部使用')
  }
  return context
}
