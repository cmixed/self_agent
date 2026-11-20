import {
  ApartmentOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileMarkdownOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileUnknownOutlined,
  FolderOpenOutlined,
  ImportOutlined,
  InboxOutlined,
  LockOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
  ShareAltOutlined,
  SwapOutlined,
  TagsOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Checkbox,
  Drawer,
  Dropdown,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import type { TableProps, UploadProps } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import ImportPreviewModal from '../components/ImportPreviewModal'
import PageContainer from '../components/PageContainer'
import PageTabs from '../components/PageTabs'
import ShareDialog from '../components/ShareDialog'
import ShareGraph from '../components/ShareGraph'
import StatStrip from '../components/StatStrip'
import { usePageRefresh } from '../hooks/usePageRefresh'
import { useViewStack } from '../components/ViewStack'
import {
  ApiError,
  confirmKnowledgeImport,
  createCategory,
  createKnowledgeBase,
  deleteCategory,
  deleteDocument,
  deleteKnowledgeBase,
  exportKnowledgeBase,
  getKnowledgeBase,
  getShareGraph,
  listCategories,
  listDocuments,
  listGroups,
  listKnowledgeBases,
  moveDocument,
  previewKnowledgeImport,
  revokeShare,
  setDocumentCategories,
  updateCategory,
  updateKnowledgeBase,
  uploadDocument,
} from '../services/api'
import { listMembers } from '../services/auth'
import type { Member } from '../services/auth'
import type {
  CategoryInfo,
  DocumentInfo,
  GroupItem,
  KnowledgeBase,
  KnowledgeBaseDetail,
  KnowledgeImportPreview,
  ShareGraphData,
} from '../types/api'
import { downloadBlob } from '../utils/download'
import { documentKind } from '../utils/format'

const { Text, Paragraph } = Typography
const { Dragger } = Upload

const PAGE_EYEBROW = '知识库'
const PAGE_TITLE = '知识库与共享'
const PAGE_DESCRIPTION =
  '每个知识库是一个独立的资料集合：上传、共享、检索范围都按库划分。共享以「库（或其中几个文件）× 一批人 × 一组能力」组合生效。'
const PAGE_MAX_WIDTH = 1280

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

interface KbFormValues {
  name: string
  description?: string
}

const CAP_TAG_COLOR: Record<string, string> = {
  可编辑: 'purple',
  只读: 'green',
  '可检索 + 看列表': 'blue',
  仅检索: 'gold',
  无权限: 'default',
}

function capsTag(label: string) {
  return (
    <Tag color={CAP_TAG_COLOR[label] ?? 'default'} className="kb-tag">
      {label}
    </Tag>
  )
}

export default function KnowledgeBasePage() {
  const { message, modal } = App.useApp()
  const { openDocument } = useViewStack()

  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [activeKbId, setActiveKbId] = useState<string>('')
  const [detail, setDetail] = useState<KnowledgeBaseDetail | null>(null)
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [groups, setGroups] = useState<GroupItem[]>([])
  const [members, setMembers] = useState<Member[]>([])
  const [graph, setGraph] = useState<ShareGraphData | null>(null)
  const [viewMode, setViewMode] = useState<'files' | 'graph'>('files')
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

  const [kbModalOpen, setKbModalOpen] = useState(false)
  const [editingKb, setEditingKb] = useState<KnowledgeBase | null>(null)
  const [kbForm] = Form.useForm<KbFormValues>()

  const [shareOpen, setShareOpen] = useState(false)
  const [sharesOpen, setSharesOpen] = useState(false)
  const [moveTarget, setMoveTarget] = useState<DocumentInfo | null>(null)
  const [moveKbId, setMoveKbId] = useState<string>('')

  const uploadQueue = useRef<Promise<void>>(Promise.resolve())

  const [importing, setImporting] = useState(false)
  const [importPreview, setImportPreview] = useState<KnowledgeImportPreview | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

  const activeKb = useMemo(
    () => kbs.find((item) => item.kb_id === activeKbId) ?? null,
    [kbs, activeKbId],
  )
  const canWrite = Boolean(activeKb?.my_caps.write)
  const canList = Boolean(activeKb?.my_caps.list)

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [kbData, categoryData, groupData, graphData] = await Promise.all([
        listKnowledgeBases(),
        listCategories(),
        listGroups().catch(() => ({ items: [] as GroupItem[] })),
        getShareGraph().catch(() => null),
      ])
      setKbs(kbData.items)
      setCategories(categoryData.categories)
      setGroups(groupData.items)
      setGraph(graphData)
      setActiveKbId((current) => {
        if (current && kbData.items.some((item) => item.kb_id === current)) return current
        return kbData.items[0]?.kb_id ?? ''
      })
      // 成员列表只有管理员能取；普通成员共享给「分组 / 全团队」即可
      try {
        setMembers(await listMembers())
      } catch {
        setMembers([])
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载知识库失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadActive = useCallback(async (kbId: string) => {
    if (!kbId) {
      setDetail(null)
      setDocuments([])
      return
    }
    try {
      const [kbDetail, docData] = await Promise.all([
        getKnowledgeBase(kbId),
        listDocuments(kbId).catch(() => ({ documents: [] as DocumentInfo[] })),
      ])
      setDetail(kbDetail)
      setDocuments(docData.documents)
      setSelectedIds([])
      setActiveCategory(FILTER_ALL)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载知识库详情失败')
    }
  }, [])

  usePageRefresh(loadAll)

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  useEffect(() => {
    void loadActive(activeKbId)
  }, [activeKbId, loadActive])

  useEffect(() => {
    if (viewMode !== 'graph') return
    void getShareGraph()
      .then(setGraph)
      .catch(() => setGraph(null))
  }, [viewMode])

  const refreshActive = useCallback(async () => {
    await loadActive(activeKbId)
    setKbs((await listKnowledgeBases()).items)
  }, [activeKbId, loadActive])

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

  // --- 上传 ---

  const runUpload = async (file: File) => {
    if (!activeKb) return
    setUploadProgress({ name: file.name, percent: 0 })
    setError(null)
    try {
      const info = await uploadDocument(file, {
        kbId: activeKb.kb_id,
        onProgress: (percent) => setUploadProgress({ name: file.name, percent }),
      })
      message.success(`已索引《${info.filename}》，切分为 ${info.chunks} 个文本块`)
      await refreshActive()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '上传失败')
    } finally {
      setUploadingCount((count) => Math.max(0, count - 1))
      setUploadProgress(null)
    }
  }

  const handleUpload = async (file: File) => {
    if (!activeKb) return
    if (!canWrite) {
      message.warning('你在这个知识库没有编辑权限，请切换到自己有编辑权的库再上传')
      return
    }
    if (documents.some((item) => item.filename === file.name)) {
      const confirmed = await new Promise<boolean>((resolve) => {
        modal.confirm({
          title: '已存在同名文档',
          content: `《${file.name}》已在该知识库中。继续上传会新建一份独立文档与向量，不会覆盖原文档。`,
          okText: '仍然上传',
          cancelText: '跳过',
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        })
      })
      if (!confirmed) return
    }
    setUploadingCount((count) => count + 1)
    const task = uploadQueue.current.then(() => runUpload(file))
    uploadQueue.current = task.catch(() => undefined)
    await uploadQueue.current
  }

  const uploadProps: UploadProps = {
    multiple: true,
    showUploadList: false,
    accept: '.pdf,.txt,.md,.markdown',
    disabled: !canWrite,
    customRequest: ({ file, onSuccess }) => {
      void handleUpload(file as File).then(() => onSuccess?.({}))
    },
  }

  // --- 删除 / 移动 ---

  const handleDelete = async (documentId: string, filename: string) => {
    setError(null)
    try {
      await deleteDocument(documentId)
      message.success(`已删除《${filename}》及其向量`)
      setSelectedIds((ids) => ids.filter((id) => id !== documentId))
      await refreshActive()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  /** 单篇删除走确认弹窗（操作收进「更多」菜单后没有 Popconfirm 可挂了）。 */
  const confirmDelete = (document: DocumentInfo) => {
    modal.confirm({
      title: `删除《${document.filename}》及其向量？`,
      content: '删除后这份文档不会再被检索到，且无法恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => handleDelete(document.document_id, document.filename),
    })
  }

  const handleBatchDelete = async () => {
    const targets = documents.filter((item) => selectedIds.includes(item.document_id))
    if (targets.length === 0) return
    let removed = 0
    for (const target of targets) {
      try {
        await deleteDocument(target.document_id)
        removed += 1
      } catch (err) {
        setError(err instanceof ApiError ? err.message : `删除《${target.filename}》失败，已停止`)
        break
      }
    }
    if (removed > 0) message.success(`已删除 ${removed} 个文档及其向量`)
    setSelectedIds([])
    await refreshActive()
  }

  const handleMove = async () => {
    if (!moveTarget || !moveKbId) return
    try {
      await moveDocument(moveTarget.document_id, moveKbId)
      const target = kbs.find((item) => item.kb_id === moveKbId)
      message.success(`已把《${moveTarget.filename}》发送到「${target?.name ?? '目标知识库'}」`)
      setMoveTarget(null)
      setMoveKbId('')
      await refreshActive()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '移动文档失败')
    }
  }

  // --- 知识库管理 ---

  const openCreateKb = () => {
    setEditingKb(null)
    kbForm.resetFields()
    setKbModalOpen(true)
  }

  const openEditKb = (kb: KnowledgeBase) => {
    setEditingKb(kb)
    kbForm.setFieldsValue({ name: kb.name, description: kb.description })
    setKbModalOpen(true)
  }

  const handleSaveKb = async (values: KbFormValues) => {
    setSaving(true)
    try {
      if (editingKb) {
        await updateKnowledgeBase(editingKb.kb_id, values)
        message.success(`已更新「${values.name}」`)
        await loadActive(editingKb.kb_id)
      } else {
        const created = await createKnowledgeBase(values)
        message.success(`已创建「${created.name}」`)
        setActiveKbId(created.kb_id)
      }
      setKbModalOpen(false)
      setEditingKb(null)
      await loadAll()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '保存知识库失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteKb = async (kb: KnowledgeBase) => {
    try {
      const result = await deleteKnowledgeBase(kb.kb_id)
      message.success(
        `已删除「${kb.name}」${result.documents_removed > 0 ? `（连同 ${result.documents_removed} 篇文档）` : ''}`,
      )
      setActiveKbId('')
      await loadAll()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '删除知识库失败')
    }
  }

  // --- 共享 ---

  const handleRevokeShare = async (shareId: string) => {
    try {
      await revokeShare(shareId)
      message.success('已撤销该共享')
      await refreshActive()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '撤销共享失败')
    }
  }

  // --- 导入 / 导出 ---

  const handleImportFile = async (file: File) => {
    setImporting(true)
    setImportError(null)
    setImportPreview(null)
    try {
      setImportPreview(await previewKnowledgeImport(file))
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '解析知识库包失败')
    } finally {
      setImporting(false)
    }
  }

  const handleConfirmImport = async () => {
    if (!importPreview) return
    setImporting(true)
    setImportError(null)
    try {
      const result = await confirmKnowledgeImport(importPreview.token)
      const failedText = result.failed.length > 0 ? `，${result.failed.length} 篇失败` : ''
      const skippedText = result.skipped.length > 0 ? `，跳过 ${result.skipped.length} 篇重复` : ''
      if (result.failed.length > 0) {
        setError(result.failed.map((item) => `《${item.filename}》：${item.message}`).join('；'))
      }
      message.success(`已导入 ${result.imported.length} 篇文档${skippedText}${failedText}`)
      setImportPreview(null)
      await refreshActive()
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '导入知识库失败')
    } finally {
      setImporting(false)
    }
  }

  const handleExport = async () => {
    setError(null)
    try {
      const { blob, filename } = await exportKnowledgeBase()
      downloadBlob(blob, filename)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '导出知识库失败')
    }
  }

  const closeImport = () => {
    if (importing) return
    setImportPreview(null)
    setImportError(null)
  }

  // --- 类别 ---

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
      await loadAll()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存类别失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteCategory = async (category: CategoryInfo) => {
    try {
      await deleteCategory(category.category_id)
      message.success(`已删除类别「${category.name}」（文档保留）`)
      if (activeCategory === category.category_id) setActiveCategory(FILTER_ALL)
      await loadAll()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除类别失败')
    }
  }

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
      await refreshActive()
    } finally {
      setSaving(false)
    }
  }

  // --- 渲染辅助 ---

  const rowSelection: TableProps<DocumentInfo>['rowSelection'] = {
    selectedRowKeys: selectedIds,
    onChange: (keys) => setSelectedIds(keys as string[]),
    preserveSelectedRowKeys: true,
  }

  const totalChunks = documents.reduce((sum, item) => sum + item.chunks, 0)
  const activeShares = (detail?.shares ?? []).filter((item) => item.status === 'active')
  const pendingShares = (detail?.shares ?? []).filter((item) => item.status === 'pending')

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

  const kbItem = (kb: KnowledgeBase) => {
    const active = kb.kb_id === activeKbId
    return (
      <button
        type="button"
        key={kb.kb_id}
        className={`kb-item${active ? ' is-active' : ''}`}
        onClick={() => setActiveKbId(kb.kb_id)}
      >
        <span className="kb-item__main">
          <span className="kb-item__name">
            {kb.kind === 'team' ? <TeamOutlined /> : <LockOutlined />}
            {kb.name}
          </span>
          <span className="kb-item__meta">
            {kb.document_count} 篇 · {kb.owner_name}
            {kb.my_caps_label ? ` · ${kb.my_caps_label}` : ''}
          </span>
        </span>
        {kb.pending_count > 0 ? <Badge count={kb.pending_count} size="small" /> : null}
      </button>
    )
  }

  const readOnlyHint = (
    <Alert
      type="info"
      showIcon
      message={`你在这个知识库只有「${activeKb?.my_caps_label}」权限`}
      description={
        activeKb?.my_caps.search && !activeKb?.my_caps.list
          ? '它仍然会参与任务检索（Agent 可以引用其中的内容），但你看不到文件列表，也打不开原文。需要更多权限请联系库主或管理员。'
          : '可以打开原文，但没有编辑权限。需要贡献内容请在自己的知识库里上传后申请共享。'
      }
    />
  )

  return (
    <PageContainer
      eyebrow={PAGE_EYEBROW}
      title={PAGE_TITLE}
      description={PAGE_DESCRIPTION}
      maxWidth={PAGE_MAX_WIDTH}
      extra={
        <Space wrap>
          <Button icon={<PlusOutlined />} onClick={openCreateKb}>
            新建知识库
          </Button>
          <Upload
            accept=".zip"
            showUploadList={false}
            beforeUpload={(file) => {
              void handleImportFile(file)
              return false
            }}
          >
            <Button icon={<ImportOutlined />} loading={importing}>
              导入
            </Button>
          </Upload>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => void handleExport()}
            disabled={documents.length === 0 && categories.length === 0}
          >
            导出
          </Button>
        </Space>
      }
    >
      {/* 顶栏分标签：文件 / 共享关系图共用团队页那套胶囊标签栏 */}
      <PageTabs
        label="知识库视图"
        activeKey={viewMode}
        onChange={(key) => setViewMode(key as 'files' | 'graph')}
        items={[
          { key: 'files', label: '文件' },
          { key: 'graph', label: '共享关系图' },
        ]}
        extra={
          <>
            <button type="button" className="tabbar__stat" onClick={() => setViewMode('files')}>
              知识库 <b>{kbs.length}</b>
            </button>
            <button type="button" className="tabbar__stat" onClick={() => setViewMode('files')}>
              文档 <b>{documents.length}</b>
            </button>
            <button type="button" className="tabbar__stat" onClick={() => setViewMode('graph')}>
              对外共享 <b>{activeShares.length}</b>
            </button>
          </>
        }
      />

      {/* 页内筛选留在内容区：顶部标签之后、列表之前 */}
      {viewMode === 'files' && canList && documents.length > 0 ? (
        <div className="page-search">
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="按文件名或标题搜索"
            aria-label="搜索文档"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
        </div>
      ) : null}

      {viewMode === 'graph' ? (
        <Card
          title="共享关系图"
          extra={
            <Space size={8}>
              <Text type="secondary">
                {graph ? `${graph.nodes.length} 个节点 · ${graph.edges.length} 条关系` : ''}
              </Text>
              {graph && graph.pending_count > 0 ? (
                <Tag color="orange">{graph.pending_count} 条待审批</Tag>
              ) : null}
            </Space>
          }
        >
          <Paragraph type="secondary" style={{ marginTop: 0 }}>
            成员 → 分组 → 知识库。实线是已生效的共享，虚线是等待管理员审批的申请；
            箭头颜色表示授予的能力。管理员能看到全部关系，但看不到库里的内容。
          </Paragraph>
          <ShareGraph
            graph={graph}
            loading={loading}
            onSelectKb={(kbId) => {
              setActiveKbId(kbId)
              setViewMode('files')
            }}
          />
        </Card>
      ) : (
        <>
          <StatStrip
            items={[
              { label: '知识库', value: kbs.length },
              { label: '当前库文档', value: documents.length },
              { label: '文本块', value: totalChunks },
              { label: '对外共享', value: activeShares.length },
            ]}
          />

          {error && (
            <ErrorNotice
              message={error}
              onClose={() => setError(null)}
              onRetry={() => void loadAll()}
            />
          )}

          <div className="kb-layout">
            <div className="kb-sidebar">
              <Card
                size="small"
                title="知识库"
                extra={
                  <Button
                    type="text"
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={openCreateKb}
                    aria-label="新建知识库"
                  />
                }
              >
                {kbs.length === 0 ? (
                  <Text type="secondary">还没有知识库，先新建一个</Text>
                ) : (
                  kbs.map(kbItem)
                )}
              </Card>
              <Card
                size="small"
                title="类别"
                extra={
                  <Button
                    type="text"
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={openCreateCategory}
                    aria-label="新建类别"
                  />
                }
              >
                {categoryFilter(FILTER_ALL, '全部文件', documents.length)}
                {categoryFilter(FILTER_NONE, '未分类', unclassifiedCount)}
                <div className="kb-category__divider" />
                {categories.length === 0 ? (
                  <Text type="secondary" className="kb-sidebar__hint">
                    还没有类别，点加号开始组织资料
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
                            {
                              key: 'delete',
                              icon: <DeleteOutlined />,
                              label: '删除类别',
                              danger: true,
                            },
                          ],
                          onClick: ({ key }) => {
                            if (key === 'rename') openEditCategory(category)
                            if (key === 'delete') void handleDeleteCategory(category)
                          },
                        }}
                      >
                        <Button
                          type="text"
                          size="small"
                          icon={<EditOutlined />}
                          aria-label="类别操作"
                        />
                      </Dropdown>
                    </div>
                  ))
                )}
              </Card>
            </div>

            <div className="kb-main">
              <Card
                title={
                  activeKb ? (
                    <Space size={8} wrap>
                      <span>{activeKb.name}</span>
                      {capsTag(activeKb.my_caps_label)}
                      {activeKb.kind === 'team' ? <Tag color="blue">团队库</Tag> : null}
                      <Text type="secondary" className="kb-title__meta">
                        {activeKb.owner_name} · {activeKb.document_count} 篇
                      </Text>
                    </Space>
                  ) : (
                    '文件'
                  )
                }
                extra={
                  activeKb ? (
                    <Space wrap>
                      <Tooltip title={canWrite ? '' : '需要编辑权限才能共享'}>
                        <Button
                          size="small"
                          icon={<ShareAltOutlined />}
                          disabled={!canWrite && !activeKb.can_manage}
                          onClick={() => setShareOpen(true)}
                        >
                          共享
                        </Button>
                      </Tooltip>
                      <Button
                        size="small"
                        icon={<ApartmentOutlined />}
                        onClick={() => setSharesOpen(true)}
                      >
                        共享情况{activeShares.length > 0 ? `（${activeShares.length}）` : ''}
                      </Button>
                      {activeKb.can_manage ? (
                        <Dropdown
                          trigger={['click']}
                          menu={{
                            items: [
                              { key: 'edit', icon: <EditOutlined />, label: '重命名 / 改描述' },
                              ...(activeKb.kind === 'team'
                                ? []
                                : [
                                    {
                                      key: 'delete',
                                      icon: <DeleteOutlined />,
                                      label: '删除知识库',
                                      danger: true,
                                    },
                                  ]),
                              {
                                key: 'category',
                                icon: <TagsOutlined />,
                                label: '新建类别',
                              },
                            ],
                            onClick: ({ key }) => {
                              if (key === 'edit') openEditKb(activeKb)
                              if (key === 'delete') void handleDeleteKb(activeKb)
                              if (key === 'category') openCreateCategory()
                            },
                          }}
                        >
                          <Button size="small" icon={<EditOutlined />} aria-label="知识库操作" />
                        </Dropdown>
                      ) : null}
                    </Space>
                  ) : null
                }
              >
                {!activeKb ? (
                  <EmptyState
                    title="还没有选中知识库"
                    hint="左侧新建一个知识库，上传资料后即可在任务中按范围检索"
                    action={
                      <Button type="primary" icon={<PlusOutlined />} onClick={openCreateKb}>
                        新建知识库
                      </Button>
                    }
                  />
                ) : (
                  <>
                    {!canList ? readOnlyHint : null}
                    {pendingShares.length > 0 ? (
                      <Alert
                        type="warning"
                        showIcon
                        message={`有 ${pendingShares.length} 条共享申请等待管理员审批`}
                        description={pendingShares
                          .map((item) => `${item.subject_name} · ${item.caps_label}`)
                          .join('；')}
                      />
                    ) : null}

                    {canList && documents.length > 0 ? (
                      <div className="kb-toolbar">
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

                    {canList && documents.length === 0 && !loading ? (
                      <EmptyState
                        title="这个知识库还没有文档"
                        hint={
                          canWrite
                            ? '在下方拖入一份论文或笔记，Agent 才能在任务里检索并标注来源'
                            : '你只有查看权限，等库主上传资料后再来'
                        }
                        action={
                          canWrite ? (
                            <Upload {...uploadProps}>
                              <Button type="primary" icon={<InboxOutlined />}>
                                上传文档
                              </Button>
                            </Upload>
                          ) : undefined
                        }
                      />
                    ) : null}

                    {canList && documents.length > 0 && filteredDocuments.length === 0 ? (
                      <EmptyState
                        compact
                        title={keyword.trim() ? '没有匹配的文档' : '该类别下还没有文档'}
                        hint={
                          keyword.trim()
                            ? `没有文件名或标题包含「${keyword.trim()}」的文档`
                            : '在文档行的「分类」里把已有资料归入这个类别'
                        }
                      />
                    ) : null}

                    {canList && filteredDocuments.length > 0 ? (
                      <Table<DocumentInfo>
                        rowKey="document_id"
                        dataSource={filteredDocuments}
                        loading={loading}
                        rowSelection={rowSelection}
                        /* 不用 x:max-content：文件名会把表撑出横向滚动条，
                           让「操作」列跑到视野外；这里让文件名换行即可。 */
                        tableLayout="fixed"
                        pagination={
                          filteredDocuments.length > 10
                            ? { pageSize: 10, showSizeChanger: false }
                            : false
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
                                  {record.caps.read ? (
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
                                  ) : (
                                    <Text>{filename}</Text>
                                  )}
                                </Space>
                              )
                            },
                          },
                          {
                            title: '类别',
                            key: 'categories',
                            width: 150,
                            render: (_, record) => {
                              const ids = record.category_ids ?? []
                              if (ids.length === 0) return <Text type="secondary">未分类</Text>
                              const shown = ids.slice(0, 2)
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
                            width: 90,
                            sorter: (a: DocumentInfo, b: DocumentInfo) => a.chunks - b.chunks,
                          },
                          {
                            title: '我的权限',
                            key: 'caps',
                            width: 120,
                            render: (_, record) =>
                              capsTag(
                                record.caps.write
                                  ? '可编辑'
                                  : record.caps.read
                                    ? '只读'
                                    : record.caps.list
                                      ? '可检索 + 看列表'
                                      : '仅检索',
                              ),
                          },
                          {
                            title: '操作',
                            key: 'action',
                            width: 176,
                            render: (_, record) => (
                              <Space size={2}>
                                {record.caps.read ? (
                                  <Button
                                    type="link"
                                    size="small"
                                    onClick={() =>
                                      openDocument({
                                        documentId: record.document_id,
                                        filename: record.filename,
                                      })
                                    }
                                  >
                                    查看
                                  </Button>
                                ) : null}
                                {record.caps.write ? (
                                  <>
                                    <Tooltip title="把这篇文档发送到另一个知识库">
                                      <Button
                                        type="link"
                                        size="small"
                                        icon={<SwapOutlined />}
                                        onClick={() => {
                                          setMoveTarget(record)
                                          setMoveKbId('')
                                        }}
                                      >
                                        发送
                                      </Button>
                                    </Tooltip>
                                    <Dropdown
                                      trigger={['click']}
                                      menu={{
                                        items: [
                                          {
                                            key: 'assign',
                                            icon: <TagsOutlined />,
                                            label: '设为类别',
                                          },
                                          {
                                            key: 'delete',
                                            icon: <DeleteOutlined />,
                                            label: '删除文档',
                                            danger: true,
                                          },
                                        ],
                                        onClick: ({ key }) => {
                                          if (key === 'assign') openAssign(record)
                                          if (key === 'delete') confirmDelete(record)
                                        },
                                      }}
                                    >
                                      <Button
                                        type="text"
                                        size="small"
                                        icon={<MoreOutlined />}
                                        aria-label="更多操作"
                                      />
                                    </Dropdown>
                                  </>
                                ) : null}
                              </Space>
                            ),
                          },
                        ]}
                      />
                    ) : null}

                    {canList && !canWrite ? (
                      <Alert
                        type="info"
                        showIcon
                        message="你在这个知识库没有编辑权限"
                        description="可以查看和检索，但不能上传、移动或删除文件。要贡献内容请在自己的知识库里上传，再申请共享给分组或团队。"
                      />
                    ) : null}
                  </>
                )}
              </Card>

              {activeKb && canWrite ? (
                <Card title={`上传到「${activeKb.name}」`}>
                  <Dragger {...uploadProps}>
                    <p className="ant-upload-drag-icon">
                      <InboxOutlined />
                    </p>
                    <Paragraph style={{ marginBottom: 4 }}>点击或拖拽文件到此区域上传</Paragraph>
                    <Text type="secondary">
                      支持 PDF / TXT / Markdown；上传后自动完成解析、分块与向量索引
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
              ) : null}
            </div>
          </div>
        </>
      )}

      {/* --- 共享 --- */}
      <ShareDialog
        open={shareOpen}
        kb={activeKb}
        documents={documents}
        groups={groups}
        members={members.map((item) => ({
          user_id: item.user_id,
          display_name: item.display_name,
        }))}
        onClose={() => setShareOpen(false)}
        onDone={() => void refreshActive()}
      />

      <Drawer
        title={detail ? `「${detail.name}」的共享` : '共享情况'}
        open={sharesOpen}
        width={560}
        onClose={() => setSharesOpen(false)}
      >
        <Paragraph type="secondary">
          共享是叠加的：同一个人可能通过多个分组或多条记录获得能力，最终按并集生效。
          撤销一条只会收回这条记录带来的能力。
        </Paragraph>
        {(detail?.shares ?? []).length === 0 ? (
          <Empty description="这个知识库还没有共享给任何人" />
        ) : (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            {(detail?.shares ?? []).map((share) => (
              <Card key={share.share_id} size="small">
                <Space size={8} wrap>
                  <Tag color={share.subject_type === 'team' ? 'blue' : 'geekblue'}>
                    {share.subject_type === 'team'
                      ? '全团队'
                      : share.subject_type === 'group'
                        ? '分组'
                        : '成员'}
                  </Tag>
                  {share.subject_type === 'team' ? null : <Text strong>{share.subject_name}</Text>}
                  {capsTag(share.caps_label)}
                  {share.status === 'pending' ? <Tag color="orange">待审批</Tag> : null}
                  {share.status === 'rejected' ? <Tag color="default">已驳回</Tag> : null}
                  {share.document_ids.length > 0 ? (
                    <Tag>{share.document_ids.length} 个文件</Tag>
                  ) : (
                    <Tag>整库</Tag>
                  )}
                </Space>
                <div style={{ marginTop: 6 }}>
                  <Text type="secondary">
                    {share.requested_by_name} 发起
                    {share.reason ? ` · ${share.reason}` : ''}
                    {share.decision_note ? ` · 审批备注：${share.decision_note}` : ''}
                  </Text>
                </div>
                {share.status !== 'rejected' && detail?.can_manage ? (
                  <div style={{ marginTop: 8 }}>
                    <Popconfirm
                      title="撤销后该主体立即失去这条共享带来的能力"
                      onConfirm={() => void handleRevokeShare(share.share_id)}
                    >
                      <Button size="small" danger type="link">
                        撤销
                      </Button>
                    </Popconfirm>
                  </div>
                ) : null}
              </Card>
            ))}
          </Space>
        )}
      </Drawer>

      {/* --- 发送到其他知识库 --- */}
      <Modal
        title={moveTarget ? `把《${moveTarget.filename}》发送到` : '发送到知识库'}
        open={moveTarget !== null}
        onCancel={() => {
          setMoveTarget(null)
          setMoveKbId('')
        }}
        onOk={() => void handleMove()}
        okText="移动"
        cancelText="取消"
        destroyOnHidden
      >
        <Paragraph type="secondary">
          文档会从当前知识库移动过去（不是复制）。你在目标知识库也需要编辑权限。
        </Paragraph>
        <Select
          style={{ width: '100%' }}
          placeholder="选择目标知识库"
          value={moveKbId || undefined}
          onChange={setMoveKbId}
          options={kbs
            .filter((kb) => kb.kb_id !== activeKbId && kb.my_caps.write)
            .map((kb) => ({
              value: kb.kb_id,
              label: `${kb.name}（${kb.document_count} 篇）`,
            }))}
          notFoundContent="你还没有其他可编辑的知识库"
        />
      </Modal>

      {/* --- 知识库新建 / 改名 --- */}
      <Modal
        title={editingKb ? `编辑「${editingKb.name}」` : '新建知识库'}
        open={kbModalOpen}
        onCancel={() => {
          setKbModalOpen(false)
          setEditingKb(null)
        }}
        onOk={() => kbForm.submit()}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={kbForm} layout="vertical" onFinish={(values) => void handleSaveKb(values)}>
          <Form.Item
            name="name"
            label="知识库名称"
            rules={[{ required: true, message: '请输入名称' }, { max: 40 }]}
          >
            <Input placeholder="例如：算法论文库 / 毕设资料" prefix={<FolderOpenOutlined />} />
          </Form.Item>
          <Form.Item name="description" label="说明（可选）" rules={[{ max: 200 }]}>
            <Input placeholder="这个库收纳什么资料、给谁用" />
          </Form.Item>
          {!editingKb ? (
            <Text type="secondary">
              新建的是你自己的知识库：默认只有你能访问，可以在「共享」里申请共享给分组或全团队。
            </Text>
          ) : null}
        </Form>
      </Modal>

      {/* --- 类别 --- */}
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
          <Text type="secondary">还没有类别，先新建一个。</Text>
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

      <ImportPreviewModal
        open={importing || importPreview !== null || importError !== null}
        title="导入知识库"
        preview={importPreview}
        importing={importing}
        error={importError}
        confirmDisabled={(importPreview?.documents.length ?? 0) === 0}
        onCancel={closeImport}
        onConfirm={() => void handleConfirmImport()}
      >
        {importPreview ? (
          <>
            <Alert
              type="info"
              showIcon
              message="确认后会重新解析、分块并建立向量索引"
              description="导入不会复用源机器的 Chroma 数据；文档会进入你自己的知识库，之后可再共享给分组。"
            />
            <Text type="secondary">
              将导入 {importPreview.documents.length} 篇文档
              {importPreview.categories.length > 0
                ? `，${importPreview.categories.length} 个类别`
                : ''}
              {importPreview.skipped.length > 0
                ? `，跳过 ${importPreview.skipped.length} 篇重复`
                : ''}
            </Text>
            {importPreview.categories.length > 0 ? (
              <div>
                <Text strong>类别</Text>
                <Space size={[6, 6]} wrap>
                  {importPreview.categories.map((name) => (
                    <Tag key={name}>{name}</Tag>
                  ))}
                </Space>
              </div>
            ) : null}
            <div>
              <Text strong>文档</Text>
              {importPreview.documents.map((item) => (
                <Card size="small" key={item.filename}>
                  <Space size={8} wrap>
                    <Text strong>{item.filename}</Text>
                    <Text type="secondary">{Math.max(1, Math.round(item.size / 1024))} KB</Text>
                    {item.category_ids.length > 0 ? (
                      <Tag>{item.category_ids.length} 个类别</Tag>
                    ) : null}
                  </Space>
                </Card>
              ))}
            </div>
            {importPreview.skipped.length > 0 ? (
              <Text type="secondary">内容已存在，将跳过：{importPreview.skipped.join('、')}</Text>
            ) : null}
          </>
        ) : null}
      </ImportPreviewModal>
    </PageContainer>
  )
}
