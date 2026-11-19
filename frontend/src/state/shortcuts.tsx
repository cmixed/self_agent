import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { getCachedUser } from '../services/auth'
import {
  hotkeysFor,
  isEditableTarget,
  isSequence,
  matchesHotkey,
  normalizeKey,
  sequenceKeys,
} from '../hotkeys'

/** 返回 false 表示「这次没消费」，事件继续交给 antd / 浏览器 */
type Handler = () => boolean | void

interface RegistryEntry {
  handler: Handler
  enabled: boolean
}

interface ShortcutValue {
  /** 注册动作处理函数（通常通过 useShortcut 使用） */
  register: (id: string, handler: Handler, enabled: boolean) => void
  unregister: (id: string) => void
  /** 主动执行动作：先找注册的处理函数，再 fallback 到 [data-hotkey] 元素 */
  run: (id: string) => boolean
  helpOpen: boolean
  setHelpOpen: (open: boolean) => void
  searchOpen: boolean
  setSearchOpen: (open: boolean) => void
}

const ShortcutContext = createContext<ShortcutValue | null>(null)

/**
 * 全局快捷键总线。
 *
 * 动作分两种注册方式：
 * 1. 应用壳用 `useShortcut(id, fn, enabled)` 注册需要读状态的动作（切页 / 返回等）；
 * 2. 页面按钮加 `data-hotkey="task.submit"`，无需改业务逻辑即可被快捷键触发。
 *
 * 同一个 id 同时存在时，注册的处理函数优先，按钮只作为兜底。
 */
export function ShortcutProvider({ children }: { children: ReactNode }) {
  const registry = useRef(new Map<string, RegistryEntry>())
  const [helpOpen, setHelpOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  // 登录态在 Provider 生命周期内不变，按角色过滤一次即可
  const defs = useMemo(() => hotkeysFor(getCachedUser()?.role === 'admin'), [])

  const register = useCallback((id: string, handler: Handler, enabled: boolean) => {
    registry.current.set(id, { handler, enabled })
  }, [])

  const unregister = useCallback((id: string) => {
    registry.current.delete(id)
  }, [])

  const run = useCallback((id: string): boolean => {
    const entry = registry.current.get(id)
    if (entry?.enabled && entry.handler() !== false) return true
    if (entry && entry.enabled === false) return false
    const element = document.querySelector<HTMLElement>(`[data-hotkey="${id}"]`)
    if (!element || element.hasAttribute('disabled')) return false
    element.click()
    return true
  }, [])

  useEffect(() => {
    // 序列键的等待状态（按下 G 之后 1.2s 内等第二个键）
    let pending: string | null = null
    let timer = 0

    const consume = (id: string): boolean => {
      const entry = registry.current.get(id)
      const hasButton = Boolean(document.querySelector(`[data-hotkey="${id}"]`))
      if (!(entry?.enabled || hasButton)) return false
      return run(id)
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat || event.isComposing) return
      // 与 self-web 一致：带 Ctrl / ⌘ / Alt 的组合一律让给浏览器，不抢系统习惯
      if (event.ctrlKey || event.metaKey || event.altKey) return

      const key = normalizeKey(event.key)
      const editable = isEditableTarget(event.target)

      // 已经按下序列前缀：这一键要么组成序列，要么作废
      if (pending) {
        const combo = `${pending} ${key}`
        pending = null
        window.clearTimeout(timer)
        const def = defs.find((item) => !item.displayOnly && item.combo === combo)
        if (def && !(editable && !def.allowInInput) && consume(def.id)) {
          event.preventDefault()
          event.stopPropagation()
        }
        return
      }

      for (const def of defs) {
        if (def.displayOnly) continue
        if (editable && !def.allowInInput) continue
        if (isSequence(def.combo)) {
          if (sequenceKeys(def.combo)[0] !== key) continue
          pending = key
          window.clearTimeout(timer)
          timer = window.setTimeout(() => {
            pending = null
          }, 1200)
          return
        }
        if (!matchesHotkey(event, def)) continue
        // 捕获阶段先问一次动作：没消费就不拦，antd 的 Esc 关弹窗仍正常工作
        if (consume(def.id)) {
          event.preventDefault()
          event.stopPropagation()
        }
        return
      }
    }
    window.addEventListener('keydown', onKeyDown, true)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('keydown', onKeyDown, true)
    }
  }, [defs, run])

  const value = useMemo<ShortcutValue>(
    () => ({ register, unregister, run, helpOpen, setHelpOpen, searchOpen, setSearchOpen }),
    [register, unregister, run, helpOpen, searchOpen],
  )
  return <ShortcutContext.Provider value={value}>{children}</ShortcutContext.Provider>
}

export function useShortcuts(): ShortcutValue {
  const context = useContext(ShortcutContext)
  if (context === null) {
    throw new Error('useShortcuts 必须在 ShortcutProvider 内部使用')
  }
  return context
}

/**
 * 注册一个动作。handler 用 ref 保存，避免每次渲染都重注册；
 * `enabled` 变化时才更新注册表（例如只在当前页面生效）。
 */
export function useShortcut(id: string, handler: Handler, enabled = true): void {
  const { register, unregister } = useShortcuts()
  const handlerRef = useRef(handler)
  handlerRef.current = handler
  useEffect(() => {
    register(id, () => handlerRef.current(), enabled)
    return () => unregister(id)
  }, [id, enabled, register, unregister])
}
