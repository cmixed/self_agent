import type { ReactNode } from 'react'

export interface PageTabItem {
  key: string
  label: ReactNode
}

interface PageTabsProps {
  /** 无障碍标签 */
  label: string
  items: PageTabItem[]
  activeKey: string
  onChange: (key: string) => void
  /** 右端状态胶囊 / 操作区 */
  extra?: ReactNode
}

/**
 * 页面顶栏标签栏（胶囊条）：横跨内容区，标签均分宽度，右端可挂状态胶囊。
 * 任务历史 / 预设任务 / 长期记忆 / 技能 / 知识库等需要「顶栏，分标签」的页面共用，
 * 与团队 / 设置的 dock 栏标签栏同一套样式（.tabbar）。
 */
export default function PageTabs({ label, items, activeKey, onChange, extra }: PageTabsProps) {
  return (
    <div className="tabbar" role="tablist" aria-label={label}>
      <div className="tabbar__tabs">
        {items.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={activeKey === item.key}
            className={`tabbar__item${activeKey === item.key ? ' is-active' : ''}`}
            onClick={() => onChange(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {extra ? <div className="tabbar__extra">{extra}</div> : null}
    </div>
  )
}
