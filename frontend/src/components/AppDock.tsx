import {
  ArrowLeftOutlined,
  MoonOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  SunOutlined,
} from '@ant-design/icons'
import { Tooltip } from 'antd'

import { formatCombo } from '../hotkeys'
import type { PageKey } from '../state/nav'
import type { ResolvedTheme } from '../theme/config'
import RunningTasks from './RunningTasks'

interface AppDockProps {
  page: PageKey
  onHelp: () => void
  onSearch: () => void
  onToggleTheme: () => void
  resolvedMode: ResolvedTheme
  onBack: () => void
  canBack: boolean
}

/**
 * 底部浮动操作坞（Liquid Glass 胶囊），三段：
 * 当前页操作（PageContainer 注入）/ 全局操作 / 任务胶囊。
 * 页面切换器已移到顶栏（PageSwitcher），dock 只留动作，不再占一整排图标。
 */
export default function AppDock({
  page,
  onHelp,
  onSearch,
  onToggleTheme,
  resolvedMode,
  onBack,
  canBack,
}: AppDockProps) {
  return (
    <div className="dock" role="toolbar" aria-label="快捷操作坞">
      <div className="dock__bar">
        {/* 段一：页面分区标签栏（成员 / 设置等多分区页面通过 portal 注入） */}
        <div
          className="dock__seg dock__seg--tabbar"
          data-page-tabbar-slot={page}
          aria-label="页面分区"
        />

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
