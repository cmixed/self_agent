import { DownloadOutlined, FileTextOutlined } from '@ant-design/icons'
import { Button, Spin } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { documentFileUrl } from '../services/api'
import { documentKind } from '../utils/format'
import EmptyState from './EmptyState'
import ErrorNotice from './ErrorNotice'
import MarkdownReader from './MarkdownReader'
import ViewHeader from './ViewHeader'
import { useViewStack } from './ViewStack'

/** 原文件文本缓存（同一文档只取一次；文档按 id 不可变）。 */
const textCache = new Map<string, string>()

/** 文档阅读视图：把原文件挑到内容区独立阅读。 */
export default function DocumentView({
  documentId,
  filename,
}: {
  documentId: string
  filename: string
}) {
  const { back } = useViewStack()
  const kind = documentKind(filename)
  const [text, setText] = useState<string | null>(() => textCache.get(documentId) ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetch(documentFileUrl(documentId))
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status))
        const body = await response.text()
        textCache.set(documentId, body)
        setText(body)
      })
      .catch(() => setError('无法读取文件内容（原文件可能已丢失）'))
      .finally(() => setLoading(false))
  }, [documentId])

  const needsLoad = kind !== 'pdf' && kind !== 'unknown' && text === null && !loading && !error
  useEffect(() => {
    if (needsLoad) load()
  }, [needsLoad, load])

  let body: ReactNode = null
  if (kind === 'pdf') {
    body = <iframe className="doc-view__frame" src={documentFileUrl(documentId)} title={filename} />
  } else if (kind === 'unknown') {
    body = <EmptyState title="暂不支持在线预览该类型" hint="可点击右上角「下载」查看原文件" />
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
        // 与任务详情用同一个阅读器（目录 + 阅读列），保证体验一致
        <MarkdownReader content={text} />
      ) : (
        <pre className="doc-view__text">{text}</pre>
      )
  }

  return (
    <div className="view-panel">
      <ViewHeader
        title={
          <>
            <FileTextOutlined className="view-header__icon" /> {filename}
          </>
        }
        subtitle="知识库原文件"
        onBack={back}
        extra={
          <Button size="small" icon={<DownloadOutlined />} href={documentFileUrl(documentId, true)}>
            下载
          </Button>
        }
      />
      <div className="view-body">{body}</div>
    </div>
  )
}
