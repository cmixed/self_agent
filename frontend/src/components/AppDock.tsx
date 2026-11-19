import {
  ArrowLeftOutlined,
  DownOutlined,
  MoonOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  SunOutlined,
} from '@ant-design/icons'
import { Button, Dropdown, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import type { ReactNode } from 'react'

import { formatCombo, PAGE_KEYS } from '../hotkeys'
import { useIsNarrow } from '../hooks/useIsNarrow'
import type { PageKey } from '../state/nav'
import type { ResolvedTheme } from '../theme/config'
import RunningTasks from './RunningTasks'

interface DockPage {
  key: PageKey
  label: string
  icon: ReactNode
}

interface AppDockProps {
  page: PageKey
  pages: DockPage[]
  onNavigate: (key: PageKey) => void
  onHelp: () => void
  onSearch: () => void
  onToggleTheme: () => void
  resolvedMode: ResolvedTheme
  onBack: () => void
  canBack: boolean
}

/**
 * 底部浮动操作坞（Liquid Glass 胶囊）。
 *
 * 四段从左到右：页面切换器 / 当前页操作 / 全局操作 / 任务胶囊。
 * - 页面切换器与快捷键 G + 字母一一对应，窄屏收进下拉；
 * - 当前页操作复用 data-page-actions-slot，PageContainer 把各页 extra 传送进来；
 * - 全局操作是常用快捷键的点击入口，提示与帮助面板同源；
 * - 任务胶囊由 RunningTasks 自行渲染（无任务时整段消失）。
 */
export default function AppDock({
  page,
  pages,
  onNavigate,
  onHelp,
  onSearch,
  onToggleTheme,
  resolvedMode,
  onBack,
  canBack,
}: AppDockProps) {
  const narrow = useIsNarrow()
  const current = pages.find((item) => item.key === page)

  const pageMenu: MenuProps['items'] = pages.map((item) => ({
    key: item.key,
    label: (
      <span className="dock__menu-label">
        {item.icon}
        {item.label}
        <kbd>{`G ${PAGE_KEYS[item.key].toUpperCase()}`}</kbd>
      </span>
    ),
  }))

  return (
    <div className="dock" role="toolbar" aria-label="快捷操作坞">
      <div className="dock__bar">
        {/* 段一：页面切换器 */}
        <div className="dock__seg dock__seg--pages">
          {narrow ? (
            <Dropdown menu={{ items: pageMenu, onClick: ({ key }) => onNavigate(key as PageKey) }}>
              <Button type="text" className="dock__nav dock__nav--current" aria-label="切换页面">
                {current?.icon}
                <span>{current?.label}</span>
                <DownOutlined />
              </Button>
            </Dropdown>
          ) : (
            pages.map((item) => (
              <Tooltip
                key={item.key}
                title={
                  <span className="dock__tip">
                    {item.label}
                    <kbd>{`G ${PAGE_KEYS[item.key].toUpperCase()}`}</kbd>
                  </span>
                }
                placement="top"
              >
                <button
                  type="button"
                  className={`dock__nav${item.key === page ? ' is-active' : ''}`}
                  aria-label={item.label}
                  aria-current={item.key === page ? 'page' : undefined}
                  onClick={() => onNavigate(item.key)}
                >
                  {item.icon}
                </button>
              </Tooltip>
            ))
          )}
        </div>

        {/* 段二：当前页操作（由 PageContainer 通过 portal 注入） */}
        <div
          className="dock__seg dock__seg--actions"
          data-page-actions-slot={page}
          aria-label="当前页面操作"
        />

        {/* 段三：全局操作 */}
        <div className="dock__seg dock__seg--global">
          <Tooltip title={`搜索（${formatCombo('/')}）`} placement="top">
            <button type="button" className="dock__action" aria-label="搜索" onClick={onSearch}>
              <SearchOutlined />
            </button>
          </Tooltip>
          <Tooltip title={`返回上一层（${formatCombo('escape')}）`} placement="top">
            <button
              type="button"
              className="dock__action"
              aria-label="返回上一层"
              disabled={!canBack}
              onClick={onBack}
            >
              <ArrowLeftOutlined />
            </button>
          </Tooltip>
          <Tooltip title={`快捷键帮助（? 或 F1）`} placement="top">
            <button type="button" className="dock__action" aria-label="快捷键帮助" onClick={onHelp}>
              <QuestionCircleOutlined />
            </button>
          </Tooltip>
          <Tooltip title={`切换主题（${formatCombo('t')}）`} placement="top">
            <button
              type="button"
              className="dock__action"
              aria-label="切换主题"
              onClick={onToggleTheme}
            >
              {resolvedMode === 'dark' ? <SunOutlined /> : <MoonOutlined />}
            </button>
          </Tooltip>
        </div>

        {/* 段四：任务胶囊（无任务时整段不渲染） */}
        <RunningTasks />
      </div>
    </div>
  )
}
