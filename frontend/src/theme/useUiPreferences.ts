import { useCallback, useEffect, useState } from 'react'

import { THEME_STORAGE_KEY } from './config'
import type { ResolvedTheme, ThemeMode } from './config'

function readStored(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    // 隐私模式等场景下 localStorage 不可用
    return fallback
  }
}

function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // 忽略写入失败，不影响使用
  }
}

/** 读取主题偏好；旧版本只存过 light/dark，缺失或非法时默认跟随系统。 */
function readMode(): ThemeMode {
  const raw = readStored(THEME_STORAGE_KEY, 'system')
  return raw === 'light' || raw === 'dark' ? raw : 'system'
}

function systemPrefersDark(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/**
 * 主题偏好（持久化到 localStorage）。
 *
 * - 默认「跟随系统」，并监听 prefers-color-scheme 实时切换；
 * - 顶栏按钮与设置页共用同一状态：按钮点击会切成明确的浅/深（离开跟随系统）；
 * - `resolvedMode` 才是真正渲染用的主题，`mode` 保留用户的原始选择。
 */
export function useUiPreferences() {
  const [mode, setMode] = useState<ThemeMode>(readMode)
  const [systemDark, setSystemDark] = useState(systemPrefersDark)

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => setSystemDark(media.matches)
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [])

  const resolvedMode: ResolvedTheme = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode

  useEffect(() => {
    writeStored(THEME_STORAGE_KEY, mode)
    document.documentElement.dataset.theme = resolvedMode
  }, [mode, resolvedMode])

  const toggleMode = useCallback(() => {
    setMode((prev) => {
      const current = prev === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : prev
      return current === 'dark' ? 'light' : 'dark'
    })
  }, [])

  return { mode, resolvedMode, setMode, toggleMode }
}
