import type { ReactNode } from 'react'

interface SectionProps {
  title: string
  description?: ReactNode
  extra?: ReactNode
}

/** 页面内的区块小标题（配合 Card / 面板使用，统一层级）。 */
export default function Section({ title, description, extra }: SectionProps) {
  return (
    <div className="section">
      <div className="section__text">
        <span className="section__title">{title}</span>
        {description ? <span className="section__desc">{description}</span> : null}
      </div>
      {extra ? <div className="section__extra">{extra}</div> : null}
    </div>
  )
}
