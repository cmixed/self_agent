// @vitest-environment happy-dom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vite-plus/test'

import { THEME_STORAGE_KEY } from './config'
import { useUiPreferences } from './useUiPreferences'

type MediaListener = (event: { matches: boolean }) => void

let prefersDark = false
const listeners = new Set<MediaListener>()

function emitSystemTheme(dark: boolean) {
  prefersDark = dark
  for (const listener of listeners) listener({ matches: dark })
}

beforeEach(() => {
  localStorage.clear()
  listeners.clear()
  prefersDark = false
  delete document.documentElement.dataset.theme
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      get matches() {
        return prefersDark
      },
      media: query,
      addEventListener: (_event: string, listener: MediaListener) => listeners.add(listener),
      removeEventListener: (_event: string, listener: MediaListener) => listeners.delete(listener),
    })),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('useUiPreferences', () => {
  it('默认跟随系统，并把实际主题写到 dataset', () => {
    const { result } = renderHook(() => useUiPreferences())

    expect(result.current.mode).toBe('system')
    expect(result.current.resolvedMode).toBe('light')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('system')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('系统主题变化时实时跟随', () => {
    const { result } = renderHook(() => useUiPreferences())

    act(() => emitSystemTheme(true))
    expect(result.current.resolvedMode).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('固定主题不受系统影响，切回跟随系统后恢复监听', () => {
    const { result } = renderHook(() => useUiPreferences())

    act(() => result.current.setMode('dark'))
    expect(result.current.mode).toBe('dark')
    expect(result.current.resolvedMode).toBe('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')

    act(() => emitSystemTheme(false))
    expect(result.current.resolvedMode).toBe('dark')

    act(() => result.current.setMode('system'))
    expect(result.current.resolvedMode).toBe('light')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('system')
  })

  it('顶栏按钮在跟随系统时切成明确的反向主题', () => {
    const { result } = renderHook(() => useUiPreferences())

    act(() => emitSystemTheme(true))
    act(() => result.current.toggleMode())
    expect(result.current.mode).toBe('light')
    expect(result.current.resolvedMode).toBe('light')

    act(() => result.current.toggleMode())
    expect(result.current.mode).toBe('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })

  it('读取已保存的主题偏好', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    const { result } = renderHook(() => useUiPreferences())

    expect(result.current.mode).toBe('dark')
    expect(result.current.resolvedMode).toBe('dark')
  })
})
