import { useCallback, useEffect, useState } from 'react'

import { THEME_STORAGE_KEY } from './config'
import type { ThemeMode } from './config'

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

/** 主题模式（持久化到 localStorage）。默认浅色（茶色），可切换到深色。 */
export function useUiPreferences() {
  const [mode, setMode] = useState<ThemeMode>(() =>
    readStored(THEME_STORAGE_KEY, 'light') === 'dark' ? 'dark' : 'light',
  )

  useEffect(() => {
    writeStored(THEME_STORAGE_KEY, mode)
    document.documentElement.dataset.theme = mode
  }, [mode])

  const toggleMode = useCallback(() => {
    setMode((prev) => (prev === 'dark' ? 'light' : 'dark'))
  }, [])

  return { mode, setMode, toggleMode }
}
