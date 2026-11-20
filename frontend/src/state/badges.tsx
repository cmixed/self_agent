import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import type { PageKey } from './nav'

export interface PageBadge {
  /** 数字徽标（>0 才显示）。 */
  count?: number
  /** 无数字时的小圆点。 */
  dot?: boolean
  /** 橙色强调（待审批 / 待入组）。 */
  warning?: boolean
}

interface BadgesValue {
  badges: Partial<Record<PageKey, PageBadge>>
  /** 页面上报自己的状态徽标；写入后持续保留，页面卸载不清空。 */
  setBadge: (page: PageKey, badge: PageBadge) => void
}

const BadgesContext = createContext<BadgesValue | null>(null)

/**
 * 模块状态徽标：页面把自己的待办数（待审批、运行中任务等）上报到这里，
 * 侧栏菜单与顶栏页面切换器从同一处读取，保证两处图标提示一致。
 *
 * 徽标写入后不随页面卸载清除——用户切走页面后仍应看到「有消息」提示。
 */
export function BadgesProvider({ children }: { children: ReactNode }) {
  const [badges, setBadges] = useState<Partial<Record<PageKey, PageBadge>>>({})
  const setBadge = useCallback((page: PageKey, badge: PageBadge) => {
    setBadges((prev) => ({ ...prev, [page]: badge }))
  }, [])
  const value = useMemo<BadgesValue>(() => ({ badges, setBadge }), [badges, setBadge])
  return <BadgesContext.Provider value={value}>{children}</BadgesContext.Provider>
}

export function useBadges(): BadgesValue {
  const context = useContext(BadgesContext)
  if (context === null) {
    throw new Error('useBadges 必须在 BadgesProvider 内部使用')
  }
  return context
}

/** 页面上报徽标的便捷 hook；badge 用 useMemo 稳定引用，避免重复写入。 */
export function useReportBadge(page: PageKey, badge: PageBadge | null) {
  const { setBadge } = useBadges()
  useEffect(() => {
    if (badge) setBadge(page, badge)
  }, [page, badge, setBadge])
}
