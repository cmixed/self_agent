import {
  FileMarkdownOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileUnknownOutlined,
  InboxOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  App,
  Badge,
  Button,
  Card,
  Popconfirm,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd'
import type { UploadProps } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { useViewStack } from '../components/ViewStack'
import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import PageContainer from '../components/PageContainer'
import StatStrip from '../components/StatStrip'
import { ApiError, deleteDocument, listDocuments, uploadDocument } from '../services/api'
import type { DocumentInfo } from '../types/api'
import { documentKind } from '../utils/format'

const { Text, Paragraph } = Typography
const { Dragger } = Upload

const PAGE_EYEBROW = '知识库'
const PAGE_TITLE = '上传资料，构建你的个人知识库'
const PAGE_DESCRIPTION = '支持 PDF / TXT / Markdown；上传后自动解析、分块并写入向量库。'
const PAGE_MAX_WIDTH = 1200

const KIND_META = {
  pdf: { icon: <FilePdfOutlined />, label: 'PDF', color: 'red' },
  markdown: { icon: <FileMarkdownOutlined />, label: 'MD', color: 'blue' },
  text: { icon: <FileTextOutlined />, label: 'TXT', color: 'default' },
  unknown: { icon: <FileUnknownOutlined />, label: '?', color: 'default' },
} as const

export default function KnowledgeBasePage() {
  const { message } = App.useApp()
  const { openDocument } = useViewStack()
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
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
    try {
      const info = await uploadDocument(file)
      message.success(`已索引《${info.filename}》，切分为 ${info.chunks} 个文本块`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handleDelete = async (documentId: string, filename: string) => {
    setError(null)
    try {
      await deleteDocument(documentId)
      message.success(`已删除《${filename}》及其向量`)
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

  const totalChunks = documents.reduce((sum, item) => sum + item.chunks, 0)
  const averageChunks = documents.length > 0 ? Math.round(totalChunks / documents.length) : 0

  return (
    <PageContainer
      eyebrow={PAGE_EYEBROW}
      title={PAGE_TITLE}
      description={PAGE_DESCRIPTION}
      maxWidth={PAGE_MAX_WIDTH}
      extra={
        <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>
          刷新
        </Button>
      }
    >
      <StatStrip
        items={[
          { label: '文档', value: loading && documents.length === 0 ? '—' : documents.length },
          { label: '文本块', value: loading && documents.length === 0 ? '—' : totalChunks },
          {
            label: '平均块 / 文档',
            value: loading && documents.length === 0 ? '—' : averageChunks,
          },
        ]}
      />

      <Card title="上传知识文档">
        <Dragger {...uploadProps}>
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <Paragraph style={{ marginBottom: 4 }}>点击或拖拽文件到此区域上传</Paragraph>
          <Text type="secondary">
            支持 PDF / TXT / Markdown；上传后自动完成文本解析、分块与向量索引
          </Text>
        </Dragger>

        {uploading && (
          <Space style={{ marginTop: 12 }} size="small">
            <Spin size="small" />
            <Text type="secondary">
              正在解析并建立索引…首次上传需加载本地 Embedding 模型（约 10 秒），请勿关闭页面
            </Text>
          </Space>
        )}
      </Card>

      {error && (
        <ErrorNotice
          message={error}
          onClose={() => setError(null)}
          onRetry={() => void refresh()}
        />
      )}

      <Card title={`知识库文档（${documents.length}）`}>
        {documents.length === 0 && !loading ? (
          <EmptyState
            title="还没有任何文档"
            hint="上传一份论文或笔记，Agent 才能在任务中检索并标注来源"
            action={
              <Upload {...uploadProps}>
                <Button type="primary" icon={<InboxOutlined />}>
                  上传文档
                </Button>
              </Upload>
            }
          />
        ) : (
          <Table<DocumentInfo>
            rowKey="document_id"
            dataSource={documents}
            loading={loading}
            scroll={{ x: 'max-content' }}
            pagination={documents.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
            columns={[
              {
                title: '文件',
                dataIndex: 'filename',
                key: 'filename',
                render: (filename: string, record) => {
                  const meta = KIND_META[documentKind(filename)]
                  return (
                    <Space size={6}>
                      <Tag color={meta.color} icon={meta.icon}>
                        {meta.label}
                      </Tag>
                      <Button
                        type="link"
                        className="doc-name"
                        onClick={() =>
                          openDocument({
                            documentId: record.document_id,
                            filename: record.filename,
                          })
                        }
                      >
                        {filename}
                      </Button>
                    </Space>
                  )
                },
              },
              { title: '标题', dataIndex: 'title', key: 'title' },
              {
                title: '文本块',
                dataIndex: 'chunks',
                key: 'chunks',
                width: 110,
                sorter: (a: DocumentInfo, b: DocumentInfo) => a.chunks - b.chunks,
                render: (chunks: number) => <Text>{chunks}</Text>,
              },
              {
                title: '状态',
                key: 'status',
                width: 110,
                // 接口只返回已成功索引的文档，故此处为真实派生状态
                render: () => <Badge status="success" text="已索引" />,
              },
              {
                title: '操作',
                key: 'action',
                width: 130,
                render: (_, record) => (
                  <Space size={4}>
                    <Button
                      type="link"
                      onClick={() =>
                        openDocument({
                          documentId: record.document_id,
                          filename: record.filename,
                        })
                      }
                    >
                      查看
                    </Button>
                    <Popconfirm
                      title="删除该文档及其向量？"
                      description="删除后该文档不会再被检索到。"
                      onConfirm={() => void handleDelete(record.document_id, record.filename)}
                    >
                      <Button danger type="link">
                        删除
                      </Button>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>
    </PageContainer>
  )
}
