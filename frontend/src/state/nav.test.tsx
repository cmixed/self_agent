// @vitest-environment happy-dom
import { cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vite-plus/test'

import { NavProvider, PAGES, useNav } from './nav'

afterEach(cleanup)

function Probe() {
  const { page, navigate } = useNav()
  return (
    <div>
      <span data-testid="page">{page}</span>
      <button type="button" onClick={() => navigate('skills')}>
        去技能页
      </button>
    </div>
  )
}

describe('NavProvider', () => {
  it('默认停在工作台', () => {
    render(
      <NavProvider>
        <Probe />
      </NavProvider>,
    )
    expect(screen.getByTestId('page').textContent).toBe('workspace')
  })

  it('navigate 切换页面', () => {
    render(
      <NavProvider>
        <Probe />
      </NavProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: '去技能页' }))
    expect(screen.getByTestId('page').textContent).toBe('skills')
  })

  it('页面 key 集合与导航项一致', () => {
    expect(PAGES).toEqual([
      'workspace',
      'knowledge',
      'skills',
      'presets',
      'providers',
      'history',
      'memory',
      'settings',
    ])
  })
})

describe('useNav', () => {
  it('在 Provider 外使用时给出明确错误', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => renderHook(() => useNav())).toThrow('useNav 必须在 NavProvider 内部使用')
    spy.mockRestore()
  })
})
