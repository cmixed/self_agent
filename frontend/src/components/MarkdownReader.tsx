import { useEffect, useMemo, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { Source } from '../types/api'
import { useViewStack } from './ViewStack'

interface TocItem {
  id: string
  text: string
  level: number
}

/**
 * Markdown 结果阅读器：左侧目录（滚动高亮）+ 右侧阅读列 + 来源互链。
 * 目录由渲染后的真实标题生成，避免重复解析 Markdown；不引入任何新依赖。
 */
export default function MarkdownReader({
  content,
  sources = [],
}: {
  content: string
  sources?: Source[]
}) {
  const articleRef = useRef<HTMLDivElement>(null)
  const [toc, setToc] = useState<TocItem[]>([])
  const [activeId, setActiveId] = useState('')
  const { openDocument } = useViewStack()

  // 将正文中的 [n] 引用指向下方「参考来源」，便于对照
  const prepared = useMemo(() => {
    if (sources.length === 0) return content
    return content.replace(/(?<!\])\[(\d+)\](?!\()/g, '[$1](#source-$1)')
  }, [content, sources.length])

  // 正文元素本身与 activeId 无关：memo 掉，滚动高亮时不再重新解析整篇 Markdown
  // （长文 final_answer 可达 150KB+，每换一个章节都重解析会明显卡顿）。
  const rendered = useMemo(
    () => <Markdown remarkPlugins={[remarkGfm]}>{prepared}</Markdown>,
    [prepared],
  )

  // 渲染后收集真实标题，生成目录并补齐锚点
  useEffect(() => {
    const root = articleRef.current
    if (!root) return
    const headings = Array.from(root.querySelectorAll('h1, h2, h3')) as HTMLElement[]
    headings.forEach((heading, index) => {
      if (!heading.id) heading.id = `md-h-${index + 1}`
    })
    setToc(
      headings.map((heading) => ({
        id: heading.id,
        text: heading.textContent ?? '',
        level: Number(heading.tagName[1]),
      })),
    )
  }, [prepared])

  // 滚动高亮当前章节
  useEffect(() => {
    const root = articleRef.current
    if (!root || toc.length === 0) return
    const headings = toc
      .map((item) => document.getElementById(item.id))
      .filter((element): element is HTMLElement => element !== null)
    if (headings.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActiveId((visible[0].target as HTMLElement).id)
      },
      { rootMargin: '-72px 0px -65% 0px', threshold: [0, 1] },
    )
    headings.forEach((heading) => observer.observe(heading))
    return () => observer.disconnect()
  }, [toc])

  const jumpTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className={`md-reader${toc.length === 0 ? ' is-single' : ''}`}>
      {toc.length > 0 ? (
        <nav className="md-reader__toc" aria-label="目录">
          <div className="md-reader__toc-head">目录</div>
          <ul>
            {toc.map((item) => (
              <li
                key={item.id}
                className={`md-reader__toc-item is-l${item.level}${
                  activeId === item.id ? ' is-active' : ''
                }`}
              >
                <button type="button" onClick={() => jumpTo(item.id)}>
                  {item.text}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}

      <div className="md-reader__main">
        <div className="markdown-body" ref={articleRef}>
          {rendered}
        </div>

        {sources.length > 0 ? (
          <section className="md-reader__refs">
            <h2 className="md-reader__refs-title">参考来源</h2>
            <ol>
              {sources.map((source) => (
                <li key={source.chunk_id} id={`source-${source.index}`}>
                  <span className="md-reader__ref-index">[{source.index}]</span>
                  <button
                    type="button"
                    className="md-reader__ref-link"
                    title={`查看《${source.filename}》`}
                    onClick={() =>
                      openDocument({ documentId: source.document_id, filename: source.filename })
                    }
                  >
                    {source.filename}
                    {source.page ? `（第 ${source.page} 页）` : ''}
                  </button>
                  {typeof source.score === 'number' ? (
                    <span className="md-reader__ref-score">相似度 {source.score.toFixed(3)}</span>
                  ) : null}
                </li>
              ))}
            </ol>
          </section>
        ) : null}
      </div>
    </div>
  )
}
