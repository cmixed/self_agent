import { DownloadOutlined } from '@ant-design/icons'
import { Button, Drawer, Space, Spin } from 'antd'
import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { useIsNarrow } from '../hooks/useIsNarrow'
import { documentFileUrl } from '../services/api'
import { documentKind } from '../utils/format'
import EmptyState from './EmptyState'
import ErrorNotice from './ErrorNotice'

export interface PreviewTarget {
  documentId: string
  filename: string
}

interface DocumentPreviewValue {
  /** 打开某个知识库文档的原文件预览（任意位置可用）。 */
  openDocument: (target: PreviewTarget) => void
}

const DocumentPreviewContext = createContext<DocumentPreviewValue | null>(null)

/**
 * 统一的文档预览：全局只挂载一次，任何出现文件名的地方都可以调用
 * ``useDocumentPreview().openDocument({ documentId, filename })`` 打开。
 *
 * - Markdown / 文本：读取原文件内容内联渲染（阅读区加宽，不再受正文 76ch 限制）
 * - PDF：浏览器内联渲染（iframe）
 * - 其他类型：提示改用下载 / 新标签打开
 * - 只读取知识库原文件，不涉及模型与向量库
 */
export function DocumentPreviewProvider({ children }: { children: ReactNode }) {
  const narrow = useIsNarrow()
  const [target, setTarget] = useState<PreviewTarget | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const openDocument = useCallback((next: PreviewTarget) => {
    setTarget(next)
    setText(null)
    setError(null)
    // PDF 交给浏览器内联渲染，无需读取文本
    if (documentKind(next.filename) === 'pdf') return
    setLoading(true)
    fetch(documentFileUrl(next.documentId))
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status))
        setText(await response.text())
      })
      .catch(() => setError('无法读取文件内容（原文件可能已丢失）'))
      .finally(() => setLoading(false))
  }, [])

  const close = useCallback(() => {
    setTarget(null)
    setText(null)
    setError(null)
  }, [])

  const value = useMemo<DocumentPreviewValue>(() => ({ openDocument }), [openDocument])

  const kind = target ? documentKind(target.filename) : 'unknown'

  const renderBody = () => {
    if (!target) return null
    if (kind === 'pdf') {
      return (
        <iframe
          className="doc-preview__frame"
          src={documentFileUrl(target.documentId)}
          title={target.filename}
        />
      )
    }
    if (kind === 'unknown') {
      return (
        <EmptyState
          title="暂不支持在线预览该类型"
          hint="可点击右上角「下载」或「新标签打开」查看原文件"
        />
      )
    }
    if (loading) {
      return (
        <div className="doc-preview__loading">
          <Spin />
        </div>
      )
    }
    if (error) {
      return <ErrorNotice message={error} onRetry={() => openDocument(target)} />
    }
    if (text === null) return null
    if (kind === 'markdown') {
      return (
        <div className="doc-preview__markdown markdown-body">
          <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
        </div>
      )
    }
    return <pre className="doc-preview__text">{text}</pre>
  }

  return (
    <DocumentPreviewContext.Provider value={value}>
      {children}
      <Drawer
        className="doc-preview-drawer"
        title={target?.filename ?? '文档预览'}
        open={target !== null}
        onClose={close}
        width={narrow ? '100%' : 1080}
        destroyOnHidden
        extra={
          target ? (
            <Space>
              <Button
                size="small"
                icon={<DownloadOutlined />}
                href={documentFileUrl(target.documentId, true)}
              >
                下载
              </Button>
              <Button size="small" href={documentFileUrl(target.documentId)} target="_blank">
                新标签打开
              </Button>
            </Space>
          ) : null
        }
      >
        {renderBody()}
      </Drawer>
    </DocumentPreviewContext.Provider>
  )
}

export function useDocumentPreview(): DocumentPreviewValue {
  const context = useContext(DocumentPreviewContext)
  if (context === null) {
    throw new Error('useDocumentPreview 必须在 DocumentPreviewProvider 内部使用')
  }
  return context
}
