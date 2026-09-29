import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MarkdownViewProps {
  content: string
}

/** 渲染最终 Markdown 结果（支持 GFM：表格、任务列表、删除线等）。 */
export default function MarkdownView({ content }: MarkdownViewProps) {
  return (
    <div className="markdown-body">
      <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
    </div>
  )
}
