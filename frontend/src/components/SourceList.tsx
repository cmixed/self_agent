import { FileTextOutlined } from '@ant-design/icons'

export interface SourceDoc {
  document_id: string
  filename: string
  /** 命中的文本块数量 */
  chunks: number
}

/** 检索到的资料：按文档聚合为简洁卡片（用于任务执行页）。 */
export default function SourceList({ docs }: { docs: SourceDoc[] }) {
  if (docs.length === 0) return null
  return (
    <ul className="source-list">
      {docs.map((doc) => (
        <li className="source-card" key={doc.document_id}>
          <span className="source-card__icon" aria-hidden="true">
            <FileTextOutlined />
          </span>
          <span className="source-card__body">
            <span className="source-card__name" title={doc.filename}>
              {doc.filename}
            </span>
            <span className="source-card__meta">{doc.chunks} 个文本块</span>
          </span>
        </li>
      ))}
    </ul>
  )
}
