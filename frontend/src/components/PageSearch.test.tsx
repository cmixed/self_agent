// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vite-plus/test'

import {
  PageSearchBar,
  PageSearchProvider,
  usePageSearch,
  usePageSearchRegistration,
} from './PageSearch'

afterEach(cleanup)

function SearchPage({ label }: { label: string }) {
  usePageSearchRegistration(label)
  return <div>页面内容</div>
}

function Harness() {
  const [showPage, setShowPage] = useState(true)
  const { hasSearch, open, keyword, toggle, closeSearch } = usePageSearch()
  return (
    <>
      <span data-testid="has-search">{hasSearch ? 'yes' : 'no'}</span>
      <span data-testid="open">{open ? 'yes' : 'no'}</span>
      <span data-testid="keyword">{keyword}</span>
      <button type="button" onClick={toggle}>
        dock 搜索
      </button>
      <button type="button" onClick={closeSearch}>
        外部关闭
      </button>
      <button type="button" onClick={() => setShowPage(false)}>
        离开页面
      </button>
      {showPage ? <SearchPage label="搜索任务内容" /> : <div>无搜索页面</div>}
      <PageSearchBar />
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
  it('默认不占空间，dock 按钮展开顶栏搜索框', () => {
    renderHarness()
    expect(screen.getByTestId('has-search').textContent).toBe('yes')
    expect(screen.getByTestId('open').textContent).toBe('no')
    expect(screen.queryByLabelText('搜索任务内容')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'dock 搜索' }))

    expect(screen.getByTestId('open').textContent).toBe('yes')
    expect(screen.getByLabelText('搜索任务内容')).toBeTruthy()
  })

  it('关闭搜索会收起输入框并清空关键词', () => {
    renderHarness()
    fireEvent.click(screen.getByRole('button', { name: 'dock 搜索' }))
    fireEvent.change(screen.getByLabelText('搜索任务内容'), { target: { value: 'RAG' } })
    expect(screen.getByTestId('keyword').textContent).toBe('RAG')

    fireEvent.click(screen.getByRole('button', { name: '关闭搜索' }))

    expect(screen.getByTestId('open').textContent).toBe('no')
    expect(screen.getByTestId('keyword').textContent).toBe('')
    expect(screen.queryByLabelText('搜索任务内容')).toBeNull()
  })

  it('页面注销后标记为无搜索，且自动收起', () => {
    renderHarness()
    fireEvent.click(screen.getByRole('button', { name: 'dock 搜索' }))
    expect(screen.getByTestId('open').textContent).toBe('yes')

    fireEvent.click(screen.getByRole('button', { name: '离开页面' }))

    expect(screen.getByTestId('has-search').textContent).toBe('no')
    expect(screen.getByTestId('open').textContent).toBe('no')
  })
})
