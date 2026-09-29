import { useCallback, useEffect, useState } from 'react'

import { MICA_STORAGE_KEY, THEME_STORAGE_KEY } from './config'
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

/** 主题模式与毛玻璃效果开关（持久化到 localStorage）。 */
export function useUiPreferences() {
  // 默认深色（可按答辩现场表现切换）
  const [mode, setMode] = useState<ThemeMode>(() =>
    readStored(THEME_STORAGE_KEY, 'dark') === 'light' ? 'light' : 'dark',
  )
  const [mica, setMica] = useState<boolean>(() => readStored(MICA_STORAGE_KEY, 'on') !== 'off')

  useEffect(() => {
    writeStored(THEME_STORAGE_KEY, mode)
    document.documentElement.dataset.theme = mode
  }, [mode])

  useEffect(() => {
    writeStored(MICA_STORAGE_KEY, mica ? 'on' : 'off')
    document.documentElement.dataset.mica = mica ? 'on' : 'off'
  }, [mica])

  const toggleMode = useCallback(() => {
    setMode((prev) => (prev === 'dark' ? 'light' : 'dark'))
  }, [])

  const toggleMica = useCallback(() => {
    setMica((prev) => !prev)
  }, [])

  return { mode, setMode, toggleMode, mica, setMica, toggleMica }
}
