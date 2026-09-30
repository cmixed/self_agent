import type { ReactNode } from 'react'

export interface StatItem {
  label: string
  value: ReactNode
  hint?: ReactNode
}

/**
 * 行内指标条：一组数字用分隔线排成一行，而不是「每个数字一张卡片」。
 * 用于页面顶部的概览指标（文档数 / 文本块 / …）。
 */
export default function StatStrip({ items }: { items: StatItem[] }) {
  if (items.length === 0) return null
  return (
    <div className="stat-strip">
      {items.map((item) => (
        <div className="stat-strip__item" key={item.label}>
          <span className="stat-strip__value">{item.value}</span>
          <span className="stat-strip__label">{item.label}</span>
          {item.hint ? <span className="stat-strip__hint">{item.hint}</span> : null}
        </div>
      ))}
    </div>
  )
}
