import {
  DeleteOutlined,
  EditOutlined,
  FileMarkdownOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileUnknownOutlined,
  FolderOpenOutlined,
  InboxOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import {
  App,
  Badge,
  Button,
  Card,
  Checkbox,
  Dropdown,
  Form,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd'
import type { TableProps, UploadProps } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useViewStack } from '../components/ViewStack'
import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import PageContainer from '../components/PageContainer'
import StatStrip from '../components/StatStrip'
import {
  ApiError,
  createCategory,
  deleteCategory,
  deleteDocument,
  listCategories,
  listDocuments,
  setDocumentCategories,
  updateCategory,
  uploadDocument,
} from '../services/api'
import type { CategoryInfo, DocumentInfo } from '../types/api'
import { documentKind } from '../utils/format'

const { Text, Paragraph } = Typography
const { Dragger } = Upload

const PAGE_EYEBROW = '知识库'
const PAGE_TITLE = '上传资料，构建你的个人知识库'
const PAGE_DESCRIPTION =
  '支持 PDF / TXT / Markdown；上传后自动解析、分块并写入向量库。可用类别自由组织，任务里按范围检索。'
const PAGE_MAX_WIDTH = 1200

/** 类别筛选：全部 / 未分类 / 具体类别 */
const FILTER_ALL = 'all'
const FILTER_NONE = 'none'

const KIND_META = {
  pdf: { icon: <FilePdfOutlined />, label: 'PDF', color: 'red' },
  markdown: { icon: <FileMarkdownOutlined />, label: 'MD', color: 'blue' },
  text: { icon: <FileTextOutlined />, label: 'TXT', color: 'default' },
  unknown: { icon: <FileUnknownOutlined />, label: '?', color: 'default' },
} as const

interface CategoryFormValues {
  name: string
  description?: string
}

export default function KnowledgeBasePage() {
  const { message, modal } = App.useApp()
  const { openDocument } = useViewStack()
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [uploadingCount, setUploadingCount] = useState(0)
  const [uploadProgress, setUploadProgress] = useState<{ name: string; percent: number } | null>(
    null,
  )
  const [error, setError] = useState<string | null>(null)
  const [activeCategory, setActiveCategory] = useState<string>(FILTER_ALL)
  const [keyword, setKeyword] = useState('')
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  const [categoryModalOpen, setCategoryModalOpen] = useState(false)
  const [editingCategory, setEditingCategory] = useState<CategoryInfo | null>(null)
  const [assignDocs, setAssignDocs] = useState<DocumentInfo[]>([])
  const [assignSelection, setAssignSelection] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [categoryForm] = Form.useForm<CategoryFormValues>()
  // 上传串行化：后一个文件等前一个「解析 + 建索引」完成，避免同时触发 Embedding
  const uploadQueue = useRef<Promise<void>>(Promise.resolve())

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [documentData, categoryData] = await Promise.all([listDocuments(), listCategories()])
      setDocuments(documentData.documents)
      setCategories(categoryData.categories)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载知识库失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const categoryNames = useMemo(
    () => Object.fromEntries(categories.map((item) => [item.category_id, item.name])),
    [categories],
  )

  const filteredDocuments = useMemo(() => {
    const inCategory =
      activeCategory === FILTER_ALL
        ? documents
        : activeCategory === FILTER_NONE
          ? documents.filter((item) => (item.category_ids ?? []).length === 0)
          : documents.filter((item) => (item.category_ids ?? []).includes(activeCategory))
    const term = keyword.trim().toLowerCase()
    if (!term) return inCategory
    return inCategory.filter(
      (item) =>
        item.filename.toLowerCase().includes(term) || item.title.toLowerCase().includes(term),
    )
  }, [activeCategory, documents, keyword])

  const unclassifiedCount = documents.filter(
    (item) => (item.category_ids ?? []).length === 0,
  ).length

  const runUpload = async (file: File) => {
    setUploadProgress({ name: file.name, percent: 0 })
    setError(null)
    try {
      const info = await uploadDocument(file, (percent) =>
        setUploadProgress({ name: file.name, percent }),
      )
      message.success(`已索引《${info.filename}》，切分为 ${info.chunks} 个文本块`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '上传失败')
    } finally {
      setUploadingCount((count) => Math.max(0, count - 1))
      setUploadProgress(null)
    }
  }

  const handleUpload = async (file: File) => {
    // 同名文档不会覆盖，会额外产生一份独立向量，先让用户确认
    if (documents.some((item) => item.filename === file.name)) {
      const confirmed = await new Promise<boolean>((resolve) => {
        modal.confirm({
          title: '已存在同名文档',
          content: `知识库中已有《${file.name}》。继续上传会新建一份独立文档与向量，不会覆盖原文档。`,
          okText: '仍然上传',
          cancelText: '跳过',
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        })
      })
      if (!confirmed) return
    }
    // 串行入队：避免多个文件同时触发 Embedding 与向量写入。
    // 入队即计数，等待中的文件也能在状态里看到（真正的进度只在轮到它时才有）。
    setUploadingCount((count) => count + 1)
    const task = uploadQueue.current.then(() => runUpload(file))
    uploadQueue.current = task.catch(() => undefined)
    await uploadQueue.current
  }

  const handleDelete = async (documentId: string, filename: string) => {
    setError(null)
    try {
      await deleteDocument(documentId)
      message.success(`已删除《${filename}》及其向量`)
      setSelectedIds((ids) => ids.filter((id) => id !== documentId))
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const handleBatchDelete = async () => {
    const targets = documents.filter((item) => selectedIds.includes(item.document_id))
    if (targets.length === 0) return
    setError(null)
    let removed = 0
    for (const target of targets) {
      try {
        await deleteDocument(target.document_id)
        removed += 1
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : `删除《${target.filename}》失败，已停止批量删除`,
        )
        break
      }
    }
    if (removed > 0) message.success(`已删除 ${removed} 个文档及其向量`)
    setSelectedIds([])
    await refresh()
  }

  // --- 类别管理 ---

  const openCreateCategory = () => {
    setEditingCategory(null)
    categoryForm.resetFields()
    setCategoryModalOpen(true)
  }

  const openEditCategory = (category: CategoryInfo) => {
    setEditingCategory(category)
    categoryForm.setFieldsValue({ name: category.name, description: category.description })
    setCategoryModalOpen(true)
  }

  const handleSaveCategory = async (values: CategoryFormValues) => {
    setSaving(true)
    setError(null)
    try {
      if (editingCategory) {
        await updateCategory(editingCategory.category_id, values)
        message.success(`已更新类别「${values.name}」`)
      } else {
        await createCategory(values)
        message.success(`已新建类别「${values.name}」`)
      }
      setCategoryModalOpen(false)
      setEditingCategory(null)
      categoryForm.resetFields()
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存类别失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteCategory = async (category: CategoryInfo) => {
    setError(null)
    try {
      await deleteCategory(category.category_id)
      message.success(`已删除类别「${category.name}」（文档保留）`)
      if (activeCategory === category.category_id) setActiveCategory(FILTER_ALL)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除类别失败')
    }
  }

  // --- 文档分类 ---

  const openAssign = (document: DocumentInfo) => {
    setAssignDocs([document])
    setAssignSelection(document.category_ids ?? [])
  }

  const openBatchAssign = () => {
    const targets = documents.filter((item) => selectedIds.includes(item.document_id))
    if (targets.length === 0) return
    setAssignDocs(targets)
    setAssignSelection([])
  }

  const handleSaveAssign = async () => {
    if (assignDocs.length === 0) return
    setSaving(true)
    setError(null)
    try {
      const results = await Promise.allSettled(
        assignDocs.map((item) => setDocumentCategories(item.document_id, assignSelection)),
      )
      const failed = results.filter((item) => item.status === 'rejected').length
      if (failed === 0) {
        message.success(
          assignDocs.length === 1
            ? `已更新《${assignDocs[0].filename}》的类别`
            : `已更新 ${assignDocs.length} 个文档的类别`,
        )
      } else {
        setError(`${failed} / ${assignDocs.length} 个文档的类别更新失败，请重试`)
      }
      setAssignDocs([])
      setSelectedIds([])
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '更新类别失败')
    } finally {
      setSaving(false)
    }
  }

  const uploadProps: UploadProps = {
    multiple: true,
    showUploadList: false,
    accept: '.pdf,.txt,.md,.markdown',
    customRequest: ({ file, onSuccess }) => {
      void handleUpload(file as File).then(() => onSuccess?.({}))
    },
  }

  const rowSelection: TableProps<DocumentInfo>['rowSelection'] = {
    selectedRowKeys: selectedIds,
    onChange: (keys) => setSelectedIds(keys as string[]),
    // 翻页后保留已选，批量操作针对的是「跨页选中的集合」
    preserveSelectedRowKeys: true,
  }

  const totalChunks = documents.reduce((sum, item) => sum + item.chunks, 0)
  const averageChunks = documents.length > 0 ? Math.round(totalChunks / documents.length) : 0

  const categoryFilter = (key: string, label: string, count: number) => (
    <button
      type="button"
      key={key}
      className={`kb-category${activeCategory === key ? ' is-active' : ''}`}
      onClick={() => setActiveCategory(key)}
    >
      <span className="kb-category__name">
        <span className="kb-category__label">{label}</span>
      </span>
      <span className="kb-category__count">{count}</span>
    </button>
  )

  return (
    <PageContainer
      eyebrow={PAGE_EYEBROW}
      title={PAGE_TITLE}
      description={PAGE_DESCRIPTION}
      maxWidth={PAGE_MAX_WIDTH}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateCategory}>
            新建类别
          </Button>
        </Space>
      }
    >
      <StatStrip
        items={[
          { label: '文档', value: loading && documents.length === 0 ? '—' : documents.length },
          { label: '文本块', value: loading && documents.length === 0 ? '—' : totalChunks },
          { label: '类别', value: loading && categories.length === 0 ? '—' : categories.length },
          {
            label: '平均块 / 文档',
            value: loading && documents.length === 0 ? '—' : averageChunks,
          },
        ]}
      />

      {error && (
        <ErrorNotice
          message={error}
          onClose={() => setError(null)}
          onRetry={() => void refresh()}
        />
      )}

      <div className="kb-layout">
        <Card size="small" title="类别" className="kb-sidebar">
          {categoryFilter(FILTER_ALL, '全部文件', documents.length)}
          {categoryFilter(FILTER_NONE, '未分类', unclassifiedCount)}
          <div className="kb-category__divider" />
          {categories.length === 0 ? (
            <Text type="secondary" className="kb-sidebar__hint">
              还没有类别，点右上角「新建类别」开始组织资料
            </Text>
          ) : (
            categories.map((category) => (
              <div key={category.category_id} className="kb-category__row">
                <button
                  type="button"
                  className={`kb-category${
                    activeCategory === category.category_id ? ' is-active' : ''
                  }`}
                  onClick={() => setActiveCategory(category.category_id)}
                >
                  <span className="kb-category__name">
                    <TagsOutlined />
                    <span className="kb-category__label">{category.name}</span>
                  </span>
                  <span className="kb-category__count">{category.document_count}</span>
                </button>
                <Dropdown
                  trigger={['click']}
                  menu={{
                    items: [
                      { key: 'rename', icon: <EditOutlined />, label: '重命名 / 改描述' },
                      { key: 'delete', icon: <DeleteOutlined />, label: '删除类别', danger: true },
                    ],
                    onClick: ({ key }) => {
                      if (key === 'rename') openEditCategory(category)
                      if (key === 'delete') void handleDeleteCategory(category)
                    },
                  }}
                >
                  <Button type="text" size="small" icon={<EditOutlined />} aria-label="类别操作" />
                </Dropdown>
              </div>
            ))
          )}
        </Card>

        <div className="kb-main">
          <Card
            title={
              activeCategory === FILTER_ALL
                ? `知识库文档（${filteredDocuments.length}）`
                : activeCategory === FILTER_NONE
                  ? `未分类文档（${filteredDocuments.length}）`
                  : `「${categoryNames[activeCategory] ?? ''}」下的文档（${filteredDocuments.length}）`
            }
          >
            {documents.length > 0 ? (
              <div className="kb-toolbar">
                <Input
                  allowClear
                  prefix={<SearchOutlined />}
                  placeholder="按文件名或标题搜索"
                  aria-label="搜索文档"
                  value={keyword}
                  onChange={(event) => setKeyword(event.target.value)}
                  className="kb-search"
                />
                {selectedIds.length > 0 ? (
                  <Space size={8} wrap>
                    <Text type="secondary">已选 {selectedIds.length} 项</Text>
                    <Button
                      size="small"
                      onClick={openBatchAssign}
                      disabled={categories.length === 0}
                    >
                      批量分类
                    </Button>
                    <Popconfirm
                      title={`删除选中的 ${selectedIds.length} 个文档及其向量？`}
                      description="删除后这些文档不会再被检索到。"
                      onConfirm={() => void handleBatchDelete()}
                    >
                      <Button size="small" danger>
                        批量删除
                      </Button>
                    </Popconfirm>
                    <Button size="small" type="text" onClick={() => setSelectedIds([])}>
                      取消选择
                    </Button>
                  </Space>
                ) : (
                  <Text type="secondary">勾选文档可批量分类或删除</Text>
                )}
              </div>
            ) : null}
            {documents.length === 0 && !loading ? (
              <EmptyState
                title="还没有任何文档"
                hint="用下方「上传知识文档」区域上传一份论文或笔记，Agent 才能在任务中检索并标注来源"
                action={
                  <Upload {...uploadProps}>
                    <Button type="primary" icon={<InboxOutlined />}>
                      上传文档
                    </Button>
                  </Upload>
                }
              />
            ) : filteredDocuments.length === 0 && !loading ? (
              <EmptyState
                compact
                title={keyword.trim() ? '没有匹配的文档' : '该类别下还没有文档'}
                hint={
                  keyword.trim()
                    ? `没有文件名或标题包含「${keyword.trim()}」的文档，换个关键词试试`
                    : '在文档行的「分类」里把已有资料归入这个类别，或先在下方上传'
                }
              />
            ) : (
              <Table<DocumentInfo>
                rowKey="document_id"
                dataSource={filteredDocuments}
                loading={loading}
                rowSelection={rowSelection}
                scroll={{ x: 'max-content' }}
                pagination={
                  filteredDocuments.length > 10 ? { pageSize: 10, showSizeChanger: false } : false
                }
                columns={[
                  {
                    title: '文件',
                    dataIndex: 'filename',
                    key: 'filename',
                    render: (filename: string, record) => {
                      const meta = KIND_META[documentKind(filename)]
                      return (
                        <Space size={6}>
                          <Tag color={meta.color} icon={meta.icon} className="kb-tag">
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
                    title: '类别',
                    key: 'categories',
                    render: (_, record) => {
                      const ids = record.category_ids ?? []
                      if (ids.length === 0) return <Text type="secondary">未分类</Text>
                      const shown = ids.slice(0, 3)
                      return (
                        <div className="kb-tag-list">
                          {shown.map((id) => (
                            <Tag key={id} className="kb-tag">
                              {categoryNames[id] ?? '已删除类别'}
                            </Tag>
                          ))}
                          {ids.length > shown.length ? (
                            <Tag bordered={false} className="kb-tag kb-tag--more">
                              +{ids.length - shown.length}
                            </Tag>
                          ) : null}
                        </div>
                      )
                    },
                  },
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
                    width: 190,
                    render: (_, record) => (
                      <Space size={4}>
                        <Button type="link" onClick={() => openAssign(record)}>
                          分类
                        </Button>
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

            {uploadingCount > 0 && (
              <div className="kb-upload-status">
                <Space size="small" wrap>
                  <Spin size="small" />
                  <Text type="secondary">
                    {uploadProgress
                      ? `《${uploadProgress.name}》上传 ${uploadProgress.percent}%，随后解析并建立索引…`
                      : '正在准备上传…'}
                    {uploadingCount > 1 ? `（排队 ${uploadingCount - 1} 个）` : ''}
                  </Text>
                </Space>
                {uploadProgress ? (
                  <Progress percent={uploadProgress.percent} size="small" showInfo={false} />
                ) : null}
                <Text type="secondary" className="kb-upload-status__hint">
                  首次上传需加载本地 Embedding 模型（约 10 秒），请勿关闭页面
                </Text>
              </div>
            )}
          </Card>
        </div>
      </div>

      <Modal
        title={editingCategory ? `编辑类别：${editingCategory.name}` : '新建类别'}
        open={categoryModalOpen}
        onCancel={() => {
          setCategoryModalOpen(false)
          setEditingCategory(null)
        }}
        onOk={() => categoryForm.submit()}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form
          form={categoryForm}
          layout="vertical"
          onFinish={(values) => void handleSaveCategory(values)}
        >
          <Form.Item
            name="name"
            label="类别名"
            rules={[{ required: true, message: '请输入类别名' }, { max: 40 }]}
          >
            <Input placeholder="例如：RAG 专题 / 论文 / 课堂笔记" prefix={<FolderOpenOutlined />} />
          </Form.Item>
          <Form.Item name="description" label="说明（可选）" rules={[{ max: 200 }]}>
            <Input placeholder="用于说明这个类别收纳什么资料" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={
          assignDocs.length === 1
            ? `设置《${assignDocs[0].filename}》的类别`
            : `为 ${assignDocs.length} 个文档设置类别`
        }
        open={assignDocs.length > 0}
        onCancel={() => setAssignDocs([])}
        onOk={() => void handleSaveAssign()}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        {categories.length === 0 ? (
          <Text type="secondary">还没有类别，先在左侧「新建类别」。</Text>
        ) : (
          <>
            {assignDocs.length > 1 ? (
              <Paragraph type="secondary" className="kb-assign__hint">
                保存会把这 {assignDocs.length} 个文档的类别统一替换为下面的选择。
              </Paragraph>
            ) : null}
            <Checkbox.Group
              value={assignSelection}
              onChange={(values) => setAssignSelection(values as string[])}
              className="kb-assign"
              options={categories.map((category) => ({
                label: category.name,
                value: category.category_id,
              }))}
            />
          </>
        )}
      </Modal>
    </PageContainer>
  )
}
