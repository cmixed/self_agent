import {
  ArrowLeftOutlined,
  MoonOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  SunOutlined,
} from '@ant-design/icons'
import { Tooltip } from 'antd'

import { formatCombo } from '../hotkeys'
import type { ResolvedTheme } from '../theme/config'
import RunningTasks from './RunningTasks'
import { usePageSearch } from './PageSearch'

interface AppDockProps {
  onHelp: () => void
  onToggleTheme: () => void
  resolvedMode: ResolvedTheme
  onBack: () => void
  canBack: boolean
}

/**
 * 底部浮动操作坞（Liquid Glass 胶囊），三段：
 * 当前页操作（PageContainer 注入）/ 全局操作 / 任务胶囊。
 *
 * 导航分层（§17）：页面切换在侧栏与顶栏，页面分区标签在内容区；
 * dock 的搜索按钮是**页内搜索**入口，调用当前页面注册的搜索框，
 * 当前页面没有搜索时置灰。全局搜索入口只在设置页提供。
 */
export default function AppDock({
  onHelp,
  onToggleTheme,
  resolvedMode,
  onBack,
  canBack,
}: AppDockProps) {
  const { hasSearch, open, toggle } = usePageSearch()

  return (
    <div className="dock" role="toolbar" aria-label="快捷操作坞">
      <div className="dock__bar">
        {/* 段一：当前页操作（由 PageContainer 通过 portal 注入） */}
        <div
          className="dock__seg dock__seg--actions"
          data-page-actions-slot
          aria-label="当前页面操作"
        />

        {/* 段二：全局操作（搜索调用当前页面的页内搜索） */}
        <div className="dock__seg dock__seg--global">
          <Tooltip
            title={
              hasSearch
                ? open
                  ? '关闭搜索'
                  : `页内搜索（${formatCombo('/')}）`
                : '当前页面没有可搜索内容'
            }
            placement="top"
          >
            {/* 原生 disabled 按钮不触发鼠标事件，包一层 span 让 Tooltip 仍能显示提示 */}
            <span className="dock__action-wrap">
              <button
                type="button"
                className={`dock__action${open ? ' is-active' : ''}`}
                aria-label={open ? '关闭搜索' : '搜索当前页面'}
                aria-pressed={open}
                disabled={!hasSearch}
                onClick={toggle}
              >
                <SearchOutlined />
              </button>
            </span>
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

        {/* 段三：任务胶囊（无任务时整段不渲染） */}
        <RunningTasks />
      </div>
    </div>
  )
}
