import { CloseOutlined, SearchOutlined } from '@ant-design/icons'
import { Button, Input } from 'antd'
import type { ReactNode } from 'react'
import { createContext, useCallback, useContext, useEffect, useState } from 'react'

interface PageSearchValue {
  /** 当前页面是否注册了页内搜索 */
  hasSearch: boolean
  /** 搜索框是否在顶栏展开 */
  open: boolean
  /** 当前页面的搜索关键词（由搜索总线统一持有，关闭时清空） */
  keyword: string
  placeholder: string
  /** 每次请求聚焦时递增，顶栏输入框据此重新聚焦 */
  focusToken: number
  setKeyword: (value: string) => void
  /** 页面挂载搜索时注册占位文案；返回清理函数 */
  register: (placeholder: string) => () => void
  /** 展开并聚焦顶栏搜索框 */
  openSearch: () => void
  /** 收起并清空搜索 */
  closeSearch: () => void
  /** dock 按钮用：展开 / 收起 */
  toggle: () => void
}

const PageSearchContext = createContext<PageSearchValue | null>(null)

/**
 * 页内搜索总线：页面只注册「我有搜索」，不占页面空间；
 * 搜索框统一渲染在顶栏，由 dock 按钮或 `/` 展开（§17 导航分层）。
 *
 * 关键词放在总线里，收起搜索 / 切换页面时统一清空，避免出现
 * 「搜索框已经关掉，但列表还被看不见的关键词过滤」。
 */
export function PageSearchProvider({ children }: { children: ReactNode }) {
  const [hasSearch, setHasSearch] = useState(false)
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [placeholder, setPlaceholder] = useState('搜索当前页面')
  const [focusToken, setFocusToken] = useState(0)

  const closeSearch = useCallback(() => {
    setOpen(false)
    setKeyword('')
  }, [])

  const register = useCallback((nextPlaceholder: string) => {
    setHasSearch(true)
    setPlaceholder(nextPlaceholder)
    return () => {
      setHasSearch(false)
      setOpen(false)
      setKeyword('')
      setPlaceholder('搜索当前页面')
    }
  }, [])

  const openSearch = useCallback(() => {
    setOpen(true)
    setFocusToken((token) => token + 1)
  }, [])

  const toggle = useCallback(() => {
    if (!hasSearch) return
    if (open) {
      closeSearch()
      return
    }
    openSearch()
  }, [closeSearch, hasSearch, open, openSearch])

  return (
    <PageSearchContext.Provider
      value={{
        hasSearch,
        open,
        keyword,
        placeholder,
        focusToken,
        setKeyword,
        register,
        openSearch,
        closeSearch,
        toggle,
      }}
    >
      {children}
    </PageSearchContext.Provider>
  )
}

export function usePageSearch(): PageSearchValue {
  const context = useContext(PageSearchContext)
  if (context === null) {
    throw new Error('usePageSearch 必须在 PageSearchProvider 内部使用')
  }
  return context
}

/**
 * 页面声明「这里有一个页内搜索」。只注册占位文案，不渲染输入框；
 * 输入框由顶栏的 `PageSearchBar` 统一渲染。
 *
 * `enabled=false` 时自动注销（例如知识库切到关系图 / 没有可搜索文档）。
 */
export function usePageSearchRegistration(placeholder: string, enabled = true): void {
  const { register } = usePageSearch()
  useEffect(() => {
    if (!enabled) return
    return register(placeholder)
  }, [enabled, placeholder, register])
}

/**
 * 顶栏搜索框：仅在当前页面注册了搜索且用户主动展开时渲染，
 * 因此不占页面空间，收起时也不占顶栏空间。
 */
export function PageSearchBar() {
  const { open, hasSearch, keyword, placeholder, focusToken, setKeyword, closeSearch } =
    usePageSearch()

  useEffect(() => {
    if (!open) return
    const input = document.querySelector<HTMLInputElement>('[data-page-search] input')
    input?.focus()
    input?.select()
  }, [focusToken, open])

  if (!open || !hasSearch) return null

  return (
    <div className="app-header-search" data-page-search>
      <Input
        allowClear
        prefix={<SearchOutlined />}
        placeholder={placeholder}
        aria-label={placeholder}
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation()
            closeSearch()
          }
        }}
      />
      <Button
        type="text"
        size="small"
        aria-label="关闭搜索"
        icon={<CloseOutlined />}
        onClick={closeSearch}
      />
    </div>
  )
}
