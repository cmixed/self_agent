import { Alert, Button, Card, Popconfirm, Table, Tag, Typography, Upload } from 'antd'
import type { UploadProps } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import PageContainer from '../components/PageContainer'

import { ApiError, deleteDocument, listDocuments, uploadDocument } from '../services/api'
import type { DocumentInfo } from '../types/api'

const { Text, Paragraph } = Typography
const { Dragger } = Upload

const PAGE_TITLE = '知识库'
const PAGE_DESCRIPTION = '上传 PDF、TXT、Markdown 文档；Agent 检索这些资料并在正文中标注来源。'
const PAGE_MAX_WIDTH = 1120

export default function KnowledgeBasePage() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listDocuments()
      setDocuments(data.documents)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载文档失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleUpload = async (file: File) => {
    setUploading(true)
    setError(null)
    setNotice(null)
    try {
      const info = await uploadDocument(file)
      setNotice(`已索引《${info.filename}》，切分为 ${info.chunks} 个文本块`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handleDelete = async (documentId: string) => {
    setError(null)
    setNotice(null)
    try {
      await deleteDocument(documentId)
      setNotice('已删除该文档及其向量')
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const uploadProps: UploadProps = {
    multiple: true,
    showUploadList: false,
    accept: '.pdf,.txt,.md,.markdown',
    disabled: uploading,
    customRequest: ({ file, onSuccess }) => {
      void handleUpload(file as File).then(() => onSuccess?.({}))
    },
  }

  return (
    <PageContainer
      title={PAGE_TITLE}
      description={PAGE_DESCRIPTION}
      maxWidth={PAGE_MAX_WIDTH}
    >
      <Card title="上传文档">
        <Dragger {...uploadProps}>
          <Paragraph style={{ marginBottom: 0 }}>
            点击或拖拽文件到此区域上传（支持 PDF / TXT / Markdown）
          </Paragraph>
          <Text type="secondary">
            {uploading
              ? '正在解析并向量化…首次上传需加载本地 Embedding 模型，可能较慢'
              : '文档会被切分并写入 ChromaDB，供 Agent 检索引用'}
          </Text>
        </Dragger>
      </Card>

      {notice && <Alert type="success" showIcon title={notice} />}
      {error && <Alert type="error" showIcon title={error} />}

      <Card
        title={`知识库文档（${documents.length}）`}
        extra={<Button onClick={() => void refresh()} loading={loading}>刷新</Button>}
      >
        <Table<DocumentInfo>
          rowKey="document_id"
          dataSource={documents}
          pagination={false}
          loading={loading}
          locale={{ emptyText: '还没有上传任何文档' }}
          columns={[
            { title: '文件名', dataIndex: 'filename', key: 'filename' },
            { title: '标题', dataIndex: 'title', key: 'title' },
            {
              title: '文本块',
              dataIndex: 'chunks',
              key: 'chunks',
              width: 100,
              render: (chunks: number) => <Tag>{chunks}</Tag>,
            },
            {
              title: '操作',
              key: 'action',
              width: 100,
              render: (_, record) => (
                <Popconfirm
                  title="删除该文档及其向量？"
                  onConfirm={() => void handleDelete(record.document_id)}
                >
                  <Button danger type="link">
                    删除
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>
    </PageContainer>
  )
}
