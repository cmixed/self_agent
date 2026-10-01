import { FileTextOutlined, RightOutlined } from '@ant-design/icons'

import { useDocumentWorkspace } from './DocumentWorkspace'

export interface SourceDoc {
  document_id: string
  filename: string
  /** 命中的文本块数量 */
  chunks: number
}

/**
 * 检索到的资料：按文档聚合为简洁卡片（用于任务执行页）。
 * 点击卡片即可打开该文档的原文件预览（统一预览组件）。
 */
export default function SourceList({ docs }: { docs: SourceDoc[] }) {
  const { openDocument } = useDocumentWorkspace()
  if (docs.length === 0) return null
  return (
    <ul className="source-list">
      {docs.map((doc) => (
        <li key={doc.document_id}>
          <button
            type="button"
            className="source-card"
            title={`查看《${doc.filename}》`}
            onClick={() =>
              openDocument({ documentId: doc.document_id, filename: doc.filename })
            }
          >
            <span className="source-card__icon" aria-hidden="true">
              <FileTextOutlined />
            </span>
            <span className="source-card__body">
              <span className="source-card__name" title={doc.filename}>
                {doc.filename}
              </span>
              <span className="source-card__meta">{doc.chunks} 个文本块</span>
            </span>
            <span className="source-card__go" aria-hidden="true">
              <RightOutlined />
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
