import { DownOutlined } from '@ant-design/icons'
import { Button, Dropdown, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import type { ReactNode } from 'react'

import { PAGE_KEYS } from '../hotkeys'
import { useIsNarrow } from '../hooks/useIsNarrow'
import type { PageKey } from '../state/nav'

export interface SwitchPage {
  key: PageKey
  label: string
  icon: ReactNode
}

interface PageSwitcherProps {
  page: PageKey
  pages: SwitchPage[]
  onNavigate: (key: PageKey) => void
}

/**
 * 顶栏页面切换器：一排紧凑图标，当前页高亮，与 G + 字母快捷键对应。
 * 窄屏收成「当前页 + 下拉」，不占顶栏宽度。
 */
export default function PageSwitcher({ page, pages, onNavigate }: PageSwitcherProps) {
  const narrow = useIsNarrow()
  const current = pages.find((item) => item.key === page)

  const menu: MenuProps['items'] = pages.map((item) => ({
    key: item.key,
    label: (
      <span className="page-switcher__menu-label">
        {item.icon}
        {item.label}
        <kbd>{`G ${PAGE_KEYS[item.key].toUpperCase()}`}</kbd>
      </span>
    ),
  }))

  if (narrow) {
    return (
      <Dropdown menu={{ items: menu, onClick: ({ key }) => onNavigate(key as PageKey) }}>
        <Button type="text" size="small" className="page-switcher__current" aria-label="切换页面">
          {current?.icon}
          <span>{current?.label}</span>
          <DownOutlined />
        </Button>
      </Dropdown>
    )
  }

  return (
    <nav className="page-switcher" role="navigation" aria-label="页面切换">
      {pages.map((item) => (
        <Tooltip
          key={item.key}
          title={
            <span className="page-switcher__tip">
              {item.label}
              <kbd>{`G ${PAGE_KEYS[item.key].toUpperCase()}`}</kbd>
            </span>
          }
          placement="bottom"
        >
          <button
            type="button"
            className={`page-switcher__item${item.key === page ? ' is-active' : ''}`}
            aria-label={item.label}
            aria-current={item.key === page ? 'page' : undefined}
            onClick={() => onNavigate(item.key)}
          >
            {item.icon}
          </button>
        </Tooltip>
      ))}
    </nav>
  )
}
