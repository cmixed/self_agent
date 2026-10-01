import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

export interface DocTarget {
  documentId: string
  filename: string
}

/** 内容区可叠加的"详情视图"（阅读/详情 = 视图，输入表单仍用 Modal）。 */
export type OverlayView =
  | { kind: 'document'; documentId: string; filename: string }
  | { kind: 'task'; taskId: string }

export interface OverlayEntry {
  id: number
  view: OverlayView
}

interface ViewStackValue {
  /** 叠加在页面之上的视图（可嵌套：任务详情 → 来源文档）。 */
  overlays: OverlayEntry[]
  canGoBack: boolean
  /** 推入一个视图（当前视图保持挂载，返回时状态不丢）。 */
  push: (view: OverlayView) => void
  /** 返回上一层。 */
  back: () => void
  /** 清空全部叠加视图，回到页面。 */
  closeAll: () => void
  openDocument: (target: DocTarget) => void
  openTask: (taskId: string) => void
}

const ViewStackContext = createContext<ViewStackValue | null>(null)

/**
 * 统一的内容区视图栈。
 *
 * 规则：**阅读 / 详情 = 内容区视图（顶部统一「← 返回」）；输入表单 = Modal**。
 * 页面始终留在栈底并保持挂载，因此返回时列表、筛选、任务进度都原样保留。
 */
export function ViewStackProvider({ children }: { children: ReactNode }) {
  const [overlays, setOverlays] = useState<OverlayEntry[]>([])
  const nextId = useRef(0)

  const push = useCallback((view: OverlayView) => {
    nextId.current += 1
    setOverlays((prev) => [...prev, { id: nextId.current, view }])
  }, [])

  const back = useCallback(() => setOverlays((prev) => prev.slice(0, -1)), [])
  const closeAll = useCallback(() => setOverlays([]), [])

  const openDocument = useCallback(
    (target: DocTarget) => push({ kind: 'document', ...target }),
    [push],
  )
  const openTask = useCallback((taskId: string) => push({ kind: 'task', taskId }), [push])

  const value = useMemo<ViewStackValue>(
    () => ({
      overlays,
      canGoBack: overlays.length > 0,
      push,
      back,
      closeAll,
      openDocument,
      openTask,
    }),
    [overlays, push, back, closeAll, openDocument, openTask],
  )

  return <ViewStackContext.Provider value={value}>{children}</ViewStackContext.Provider>
}

export function useViewStack(): ViewStackValue {
  const context = useContext(ViewStackContext)
  if (context === null) {
    throw new Error('useViewStack 必须在 ViewStackProvider 内部使用')
  }
  return context
}
