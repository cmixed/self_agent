import { ArrowLeftOutlined, DownloadOutlined, FileTextOutlined } from '@ant-design/icons'
import { Button, Space, Spin } from 'antd'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { documentFileUrl } from '../services/api'
import { documentKind } from '../utils/format'
import EmptyState from './EmptyState'
import ErrorNotice from './ErrorNotice'

export interface DocTarget {
  documentId: string
  filename: string
}

interface WorkspaceValue {
  /** 打开一个知识库文档（全内容区阅读；再次打开会替换当前文档）。 */
  openDocument: (target: DocTarget) => void
  /** 关闭当前文档，返回原页面。 */
  closeDocument: () => void
  document: DocTarget | null
  hasDocument: boolean
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null)

/** 原文件文本缓存（同一文档只取一次；文档按 id 不可变）。 */
const textCache = new Map<string, string>()

/**
 * 文档工作区：把文档"挑出来"在内容区独立阅读，而不是浮层预览。
 *
 * 一次只阅读一篇（与"打开 → 查看 → 返回"的心智一致），
 * 任何入口都走同一个视图与同一个「返回」：
 *   useDocumentWorkspace().openDocument({ documentId, filename })
 */
export function DocumentWorkspaceProvider({ children }: { children: ReactNode }) {
  const [doc, setDoc] = useState<DocTarget | null>(null)

  const openDocument = useCallback((target: DocTarget) => setDoc(target), [])
  const closeDocument = useCallback(() => setDoc(null), [])

  const value = useMemo<WorkspaceValue>(
    () => ({ openDocument, closeDocument, document: doc, hasDocument: doc !== null }),
    [openDocument, closeDocument, doc],
  )

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}

export function useDocumentWorkspace(): WorkspaceValue {
  const context = useContext(WorkspaceContext)
  if (context === null) {
    throw new Error('useDocumentWorkspace 必须在 DocumentWorkspaceProvider 内部使用')
  }
  return context
}

function DocumentViewer({ doc, onClose }: { doc: DocTarget; onClose: () => void }) {
  const kind = documentKind(doc.filename)
  const [text, setText] = useState<string | null>(() => textCache.get(doc.documentId) ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetch(documentFileUrl(doc.documentId))
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status))
        const body = await response.text()
        textCache.set(doc.documentId, body)
        setText(body)
      })
      .catch(() => setError('无法读取文件内容（原文件可能已丢失）'))
      .finally(() => setLoading(false))
  }, [doc.documentId])

  const needsLoad = kind !== 'pdf' && kind !== 'unknown' && text === null && !loading && !error
  useEffect(() => {
    if (needsLoad) load()
  }, [needsLoad, load])

  let body: ReactNode = null
  if (kind === 'pdf') {
    body = (
      <iframe
        className="doc-view__frame"
        src={documentFileUrl(doc.documentId)}
        title={doc.filename}
      />
    )
  } else if (kind === 'unknown') {
    body = (
      <EmptyState
        title="暂不支持在线预览该类型"
        hint="可点击右上角「下载」或「新标签打开」查看原文件"
      />
    )
  } else if (loading) {
    body = (
      <div className="doc-view__loading">
        <Spin />
      </div>
    )
  } else if (error) {
    body = <ErrorNotice message={error} onRetry={load} />
  } else if (text !== null) {
    body =
      kind === 'markdown' ? (
        <div className="doc-view__markdown markdown-body">
          <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
        </div>
      ) : (
        <pre className="doc-view__text">{text}</pre>
      )
  }

  return (
    <div className="doc-view">
      <div className="doc-view__head">
        <div className="doc-view__title">
          <Button
            size="small"
            type="text"
            className="doc-view__back"
            icon={<ArrowLeftOutlined />}
            onClick={onClose}
          >
            返回
          </Button>
          <span className="doc-view__divider" aria-hidden="true" />
          <span className="doc-view__icon" aria-hidden="true">
            <FileTextOutlined />
          </span>
          <span className="doc-view__name" title={doc.filename}>
            {doc.filename}
          </span>
        </div>
        <Space>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            href={documentFileUrl(doc.documentId, true)}
          >
            下载
          </Button>
          <Button size="small" href={documentFileUrl(doc.documentId)} target="_blank">
            新标签打开
          </Button>
        </Space>
      </div>
      <div className="doc-view__body">{body}</div>
    </div>
  )
}

/** 当前打开的文档（由 AppShell 在内容区渲染）。 */
export function DocumentWorkspace() {
  const { document: doc, closeDocument } = useDocumentWorkspace()
  if (doc === null) return null
  return <DocumentViewer key={doc.documentId} doc={doc} onClose={closeDocument} />
}
