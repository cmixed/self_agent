// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vite-plus/test'

import { PageSearchField, PageSearchProvider, usePageSearch } from './PageSearch'

afterEach(cleanup)

function Harness() {
  const [showField, setShowField] = useState(true)
  const { hasSearch, trigger } = usePageSearch()
  return (
    <>
      <span data-testid="has-search">{hasSearch ? 'yes' : 'no'}</span>
      <button type="button" onClick={trigger}>
        搜索
      </button>
      <button type="button" onClick={() => setShowField(false)}>
        卸载搜索框
      </button>
      {showField ? (
        <PageSearchField>
          <input aria-label="页内搜索" />
        </PageSearchField>
      ) : null}
    </>
  )
}

function renderHarness() {
  return render(
    <PageSearchProvider>
      <Harness />
    </PageSearchProvider>,
  )
}

describe('PageSearchProvider', () => {
  it('页内搜索框挂载后可被 dock / 快捷键聚焦', () => {
    renderHarness()
    expect(screen.getByTestId('has-search').textContent).toBe('yes')

    const input = screen.getByLabelText('页内搜索')
    expect(document.activeElement).not.toBe(input)

    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    expect(document.activeElement).toBe(input)
  })

  it('搜索框卸载后标记为无搜索，触发不再报错', () => {
    renderHarness()
    fireEvent.click(screen.getByRole('button', { name: '卸载搜索框' }))

    expect(screen.getByTestId('has-search').textContent).toBe('no')
    expect(() => fireEvent.click(screen.getByRole('button', { name: '搜索' }))).not.toThrow()
  })
})
