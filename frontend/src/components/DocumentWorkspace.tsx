import { CloseOutlined, DownloadOutlined, FileTextOutlined } from '@ant-design/icons'
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
  /** 打开某个知识库文档（已打开则直接切换过去）。 */
  openDocument: (target: DocTarget) => void
  /** 关闭某个已打开的文档。 */
  closeDocument: (documentId: string) => void
  /** 关闭全部文档，返回当前页面。 */
  closeAll: () => void
  /** 切换当前活动文档。 */
  showDocument: (documentId: string) => void
  documents: DocTarget[]
  activeDocument: DocTarget | null
  /** 当前是否有文档处于打开状态（此时内容区展示文档工作区）。 */
  hasDocuments: boolean
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null)

/** 原文件文本缓存（同一文档只取一次；文档按 id 不可变）。 */
const textCache = new Map<string, string>()

/**
 * 文档工作区：像编辑器一样把文档"挑出来"在内容区阅读，而不是浮层预览。
 *
 * - 在 App 层挂载一次；
 * - 任意位置 `useDocumentWorkspace().openDocument({ documentId, filename })` 即可打开；
 * - 内容区由 AppShell 决定渲染页面还是文档工作区（标签页 + 阅读视图 + 关闭）。
 */
export function DocumentWorkspaceProvider({ children }: { children: ReactNode }) {
  const [documents, setDocuments] = useState<DocTarget[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)

  const openDocument = useCallback((target: DocTarget) => {
    setDocuments((prev) =>
      prev.some((item) => item.documentId === target.documentId) ? prev : [...prev, target],
    )
    setActiveId(target.documentId)
  }, [])

  const closeDocument = useCallback((documentId: string) => {
    setDocuments((prev) => prev.filter((item) => item.documentId !== documentId))
    // 关闭的不是当前文档时保持选中不变；是当前文档时回退到剩余最后一个
    setActiveId((current) => (current === documentId ? null : current))
  }, [])

  const closeAll = useCallback(() => {
    setDocuments([])
    setActiveId(null)
  }, [])

  const showDocument = useCallback((documentId: string) => setActiveId(documentId), [])

  const activeDocument =
    documents.find((item) => item.documentId === activeId) ??
    documents[documents.length - 1] ??
    null

  const value = useMemo<WorkspaceValue>(
    () => ({
      openDocument,
      closeDocument,
      closeAll,
      showDocument,
      documents,
      activeDocument,
      hasDocuments: documents.length > 0,
    }),
    [openDocument, closeDocument, closeAll, showDocument, documents, activeDocument],
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

function DocumentViewer({ doc }: { doc: DocTarget }) {
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
          <span className="doc-view__icon" aria-hidden="true">
            <FileTextOutlined />
          </span>
          <span className="doc-view__name">{doc.filename}</span>
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

/** 文档工作区：标签页 + 当前文档视图。由 AppShell 在内容区渲染。 */
export function DocumentWorkspace() {
  const { documents, activeDocument, showDocument, closeDocument, closeAll } =
    useDocumentWorkspace()

  return (
    <div className="doc-workspace">
      <div className="doc-tabs" role="tablist" aria-label="打开的文档">
        {documents.map((doc) => {
          const isActive = doc.documentId === activeDocument?.documentId
          return (
            <div key={doc.documentId} className={`doc-tab${isActive ? ' is-active' : ''}`}>
              <button
                type="button"
                role="tab"
                aria-selected={isActive}
                className="doc-tab__label"
                title={doc.filename}
                onClick={() => showDocument(doc.documentId)}
              >
                <FileTextOutlined />
                <span className="doc-tab__name">{doc.filename}</span>
              </button>
              <button
                type="button"
                className="doc-tab__close"
                aria-label={`关闭 ${doc.filename}`}
                onClick={() => closeDocument(doc.documentId)}
              >
                <CloseOutlined />
              </button>
            </div>
          )
        })}
        <button type="button" className="doc-tabs__close-all" onClick={closeAll}>
          关闭全部
        </button>
      </div>

      {activeDocument ? (
        <DocumentViewer key={activeDocument.documentId} doc={activeDocument} />
      ) : null}
    </div>
  )
}
