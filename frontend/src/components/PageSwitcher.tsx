import { DownOutlined } from '@ant-design/icons'
import { Badge, Button, Dropdown, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import type { ReactNode } from 'react'

import { PAGE_KEYS } from '../hotkeys'
import { useIsNarrow } from '../hooks/useIsNarrow'
import type { PageKey } from '../state/nav'
import type { PageBadge } from '../state/badges'

export interface SwitchPage {
  key: PageKey
  label: string
  icon: ReactNode
}

interface PageSwitcherProps {
  page: PageKey
  pages: SwitchPage[]
  badges: Partial<Record<PageKey, PageBadge>>
  onNavigate: (key: PageKey) => void
}

/** 给图标裹上待办徽标；无消息时原样返回。 */
function withBadge(icon: ReactNode, badge?: PageBadge): ReactNode {
  if (badge?.count != null && badge.count > 0) {
    return (
      <Badge
        count={badge.count}
        size="small"
        offset={[2, -2]}
        color={badge.warning ? 'orange' : undefined}
      >
        {icon}
      </Badge>
    )
  }
  if (badge?.dot) {
    return (
      <Badge dot offset={[2, -2]}>
        {icon}
      </Badge>
    )
  }
  return icon
}

/**
 * 顶栏页面切换器：一排紧凑图标，当前页高亮，与 G + 字母快捷键对应。
 * 有消息的模块在图标上显示徽标，与侧栏同源。窄屏收成「当前页 + 下拉」。
 */
export default function PageSwitcher({ page, pages, badges, onNavigate }: PageSwitcherProps) {
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
          {withBadge(current?.icon, badges[page])}
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
            {withBadge(item.icon, badges[item.key])}
          </button>
        </Tooltip>
      ))}
    </nav>
  )
}
