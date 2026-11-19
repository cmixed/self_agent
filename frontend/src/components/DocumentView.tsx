import { DownloadOutlined, FileTextOutlined } from '@ant-design/icons'
import { Button, Spin } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { documentFileUrl } from '../services/api'
import { authFetch } from '../services/auth'
import { documentKind } from '../utils/format'
import EmptyState from './EmptyState'
import ErrorNotice from './ErrorNotice'
import MarkdownReader from './MarkdownReader'
import ViewHeader from './ViewHeader'
import { useViewStack } from './ViewStack'

/** 原文件文本缓存（同一文档只取一次；文档按 id 不可变）。 */
const textCache = new Map<string, string>()

const LOAD_FAILED = '无法读取文件内容（原文件可能已丢失）'

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
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 原文件接口要按 read 能力鉴权，必须带令牌；裸 fetch 会 401，
  // 之前这里就是漏了 authFetch，导致所有文档都报「原文件已丢失」。
  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    authFetch(documentFileUrl(documentId))
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status))
        const body = await response.text()
        textCache.set(documentId, body)
        setText(body)
      })
      .catch(() => setError(LOAD_FAILED))
      .finally(() => setLoading(false))
  }, [documentId])

  // PDF 同样不能直接把带鉴权的地址交给 iframe，先取回 blob 再换 object URL
  useEffect(() => {
    if (kind !== 'pdf') return
    let alive = true
    let objectUrl: string | null = null
    setPdfUrl(null)
    setError(null)
    authFetch(documentFileUrl(documentId))
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status))
        return response.blob()
      })
      .then((blob) => {
        if (!alive) return
        objectUrl = URL.createObjectURL(blob)
        setPdfUrl(objectUrl)
      })
      .catch(() => {
        if (alive) setError(LOAD_FAILED)
      })
    return () => {
      alive = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [documentId, kind])

  const download = useCallback(async () => {
    setError(null)
    try {
      const response = await authFetch(documentFileUrl(documentId, true))
      if (!response.ok) throw new Error(String(response.status))
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('下载失败，原文件可能已丢失')
    }
  }, [documentId, filename])

  const needsLoad = kind !== 'pdf' && kind !== 'unknown' && text === null && !loading && !error
  useEffect(() => {
    if (needsLoad) load()
  }, [needsLoad, load])

  let body: ReactNode = null
  if (kind === 'pdf') {
    body = error ? (
      <ErrorNotice
        message={error}
        onRetry={() => {
          setError(null)
          setPdfUrl(null)
        }}
      />
    ) : pdfUrl ? (
      <iframe className="doc-view__frame" src={pdfUrl} title={filename} />
    ) : (
      <div className="doc-view__loading">
        <Spin />
      </div>
    )
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
          <Button size="small" icon={<DownloadOutlined />} onClick={() => void download()}>
            下载
          </Button>
        }
      />
      <div className="view-body">{body}</div>
    </div>
  )
}
