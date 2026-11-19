import { Empty, Input, Modal } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useEffect, useMemo, useState } from 'react'

import { PAGE_LABELS, PAGE_ORDER, formatHotkey, hotkeysFor } from '../hotkeys'
import { getCachedUser } from '../services/auth'
import { listKnowledgeBases } from '../services/api'
import { useNav } from '../state/nav'
import { useShortcuts } from '../state/shortcuts'
import { useViewStack } from './ViewStack'
import type { KnowledgeBase } from '../types/api'

interface SearchItem {
  id: string
  title: string
  subtitle: string
  kind: 'page' | 'shortcut' | 'kb'
  execute: () => void
}

/** 按 `/` 打开的全局搜索：页面 / 知识库 / 快捷键三类结果，键盘全程可操作 */
export default function QuickSearch() {
  const { searchOpen, setSearchOpen, run } = useShortcuts()
  const { page, navigate } = useNav()
  const { closeAll } = useViewStack()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [loadingKbs, setLoadingKbs] = useState(false)
  const isAdmin = getCachedUser()?.role === 'admin'
  const defs = useMemo(() => hotkeysFor(isAdmin), [isAdmin])

  useEffect(() => {
    if (!searchOpen) return
    let alive = true
    setQuery('')
    setActive(0)
    setLoadingKbs(true)
    listKnowledgeBases()
      .then((data) => {
        if (alive) setKbs(data.items ?? [])
      })
      .catch(() => {
        if (alive) setKbs([])
      })
      .finally(() => {
        if (alive) setLoadingKbs(false)
      })
    return () => {
      alive = false
    }
  }, [searchOpen])

  const items = useMemo<SearchItem[]>(() => {
    const pages: SearchItem[] = PAGE_ORDER.filter((key) => isAdmin || key !== 'team').map(
      (key) => ({
        id: `page:${key}`,
        title: PAGE_LABELS[key],
        subtitle: '页面',
        kind: 'page',
        execute: () => {
          closeAll()
          navigate(key)
        },
      }),
    )
    const shortcuts: SearchItem[] = defs
      .filter((def) => !def.displayOnly && (!def.scope || def.scope === page))
      .map((def) => ({
        id: `hotkey:${def.id}`,
        title: def.title,
        subtitle: `快捷键 · ${formatHotkey(def)}`,
        kind: 'shortcut',
        execute: () => run(def.id),
      }))
    const libraries: SearchItem[] = kbs.map((kb) => ({
      id: `kb:${kb.kb_id}`,
      title: kb.name,
      subtitle: `知识库 · ${kb.document_count} 篇`,
      kind: 'kb',
      execute: () => {
        closeAll()
        navigate('knowledge')
      },
    }))
    const all = [...pages, ...shortcuts, ...libraries]
    const keyword = query.trim().toLowerCase()
    const matched = keyword
      ? all.filter((item) => `${item.title} ${item.subtitle}`.toLowerCase().includes(keyword))
      : all
    return matched.slice(0, 12)
  }, [query, defs, kbs, isAdmin, page, navigate, closeAll, run])

  const choose = (item?: SearchItem) => {
    if (!item) return
    setSearchOpen(false)
    item.execute()
  }

  return (
    <Modal
      open={searchOpen}
      footer={null}
      title={null}
      width={560}
      closable={false}
      onCancel={() => setSearchOpen(false)}
      styles={{ body: { padding: 0 } }}
    >
      <div className="quick-search">
        <div className="quick-search__input">
          <Input
            autoFocus
            size="large"
            variant="borderless"
            prefix={<SearchOutlined />}
            placeholder="搜索页面、知识库、快捷键…"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setActive(0)
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setActive((index) => Math.min(index + 1, items.length - 1))
              } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                setActive((index) => Math.max(index - 1, 0))
              } else if (event.key === 'Enter') {
                event.preventDefault()
                choose(items[active])
              }
            }}
          />
        </div>
        <div className="quick-search__results">
          {loadingKbs && !query ? <div className="quick-search__hint">加载知识库…</div> : null}
          {items.length === 0 ? (
            <Empty description="没有匹配结果" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : null}
          {items.map((item, index) => (
            <button
              type="button"
              key={item.id}
              className={`quick-search__item${index === active ? ' is-active' : ''}`}
              onMouseEnter={() => setActive(index)}
              onClick={() => choose(item)}
            >
              <span className={`quick-search__kind is-${item.kind}`}>
                {item.kind === 'page' ? '页' : item.kind === 'kb' ? '库' : '键'}
              </span>
              <span className="quick-search__title">{item.title}</span>
              <span className="quick-search__subtitle">{item.subtitle}</span>
            </button>
          ))}
        </div>
        <div className="quick-search__footer">
          <span>↑↓ 选择</span>
          <span>Enter 打开</span>
          <span>Esc 关闭</span>
        </div>
      </div>
    </Modal>
  )
}
