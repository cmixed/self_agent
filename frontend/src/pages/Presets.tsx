import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  HolderOutlined,
  ImportOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Skeleton,
  Space,
  Tag,
  Typography,
  Upload,
} from 'antd'
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import type { DragEndEvent } from '@dnd-kit/core'
import {
  rectSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useCallback, useEffect, useMemo, useState } from 'react'

import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import ImportPreviewModal from '../components/ImportPreviewModal'
import PageContainer from '../components/PageContainer'
import ScopePicker from '../components/ScopePicker'
import { setCachedPresets } from '../hooks/usePresets'
import {
  ApiError,
  confirmPresetImport,
  createPreset,
  deletePreset,
  exportPresets,
  listCategories,
  listDocuments,
  listPresets,
  previewPresetImport,
  reorderPresets,
  updatePreset,
} from '../services/api'
import type {
  CategoryInfo,
  DocumentInfo,
  OutputMode,
  PresetImportPreview,
  PresetInfo,
  TaskScope,
} from '../types/api'
import { formatDateTime } from '../utils/format'
import { downloadBlob } from '../utils/download'
import { filterPresetsByMode, movePreset } from '../utils/presets'
import { describeScope } from '../utils/scope'

const { Text, Paragraph } = Typography

const PAGE_EYEBROW = '预设任务'
const PAGE_TITLE = '管理工作台的快捷任务'
const PAGE_DESCRIPTION =
  '预设按「生成内容 / 直接输出知识库原文」分开管理，工作台只展示当前模式的预设。点击卡片只填入输入框，点卡片上的「直接运行」才立即执行。'
const PAGE_MAX_WIDTH = 1200

const EMPTY_SCOPE: TaskScope = { category_ids: [], document_ids: [] }

type ScopeFilter = 'all' | 'unbound' | 'bound'

interface PresetFormValues {
  title: string
  description: string
  query: string
}

/** 范围两者皆空 = 未绑定。 */
function isBound(scope: TaskScope | null | undefined): boolean {
  return Boolean(scope && scope.category_ids.length + scope.document_ids.length > 0)
}

interface SortablePresetCardProps {
  preset: PresetInfo
  categories: CategoryInfo[]
  documents: DocumentInfo[]
  canReorder: boolean
  onEdit: (preset: PresetInfo) => void
  onDelete: (preset: PresetInfo) => void
}

/** 单张预设卡片：仅左上角手柄可拖拽，避免点击编辑 / 删除时误触排序。 */
function SortablePresetCard({
  preset,
  categories,
  documents,
  canReorder,
  onEdit,
  onDelete,
}: SortablePresetCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: preset.preset_id,
    disabled: !canReorder,
  })
  const scopeInfo = describeScope(preset.scope, categories, documents)
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  return (
    <Card
      ref={setNodeRef}
      size="small"
      style={style}
      className={`entity-card${isDragging ? ' is-dragging' : ''}`}
    >
      <div className="entity-card__head">
        <Text strong className="entity-card__title" title={preset.title}>
          {preset.title}
        </Text>
        <Space size={0} className="entity-card__tools">
          <Button
            size="small"
            type="text"
            icon={<HolderOutlined />}
            aria-label="拖拽排序"
            className="preset-drag-handle"
            disabled={!canReorder}
            {...attributes}
            {...listeners}
          />
          <Button
            size="small"
            type="text"
            icon={<EditOutlined />}
            aria-label="编辑"
            onClick={() => onEdit(preset)}
          />
          <Popconfirm
            title={`删除预设「${preset.title}」？`}
            description="删除后工作台不再显示该预设"
            okText="删除"
            cancelText="取消"
            onConfirm={() => onDelete(preset)}
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />} aria-label="删除" />
          </Popconfirm>
        </Space>
      </div>

      <Paragraph
        type="secondary"
        className="entity-card__desc"
        ellipsis={{ rows: 2, tooltip: preset.description }}
      >
        {preset.description}
      </Paragraph>

      <div className="entity-card__badges">
        {preset.output_mode === 'verbatim' ? <Tag color="cyan">原文输出</Tag> : null}
        {scopeInfo.bound ? (
          <Tag color={scopeInfo.invalid ? 'orange' : 'default'}>范围：{scopeInfo.label}</Tag>
        ) : (
          <Tag>全部知识库</Tag>
        )}
      </div>

      <Text code className="entity-card__preview" ellipsis={{ tooltip: preset.query }}>
        {preset.query}
      </Text>
      <Text type="secondary" className="entity-card__meta">
        更新于 {formatDateTime(preset.updated_at)}
      </Text>
    </Card>
  )
}

export default function PresetsPage() {
  const { message } = App.useApp()
  const [presets, setPresets] = useState<PresetInfo[]>([])
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [outputMode, setOutputMode] = useState<OutputMode>('generate')
  const [filter, setFilter] = useState<ScopeFilter>('all')
  const [sorting, setSorting] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<PresetInfo | null>(null)
  const [saving, setSaving] = useState(false)
  const [formScope, setFormScope] = useState<TaskScope>(EMPTY_SCOPE)
  const [formOutputMode, setFormOutputMode] = useState<OutputMode>('generate')
  const [scopePickerOpen, setScopePickerOpen] = useState(false)
  const [form] = Form.useForm<PresetFormValues>()

  // --- 导入 / 导出 ---
  const [importing, setImporting] = useState(false)
  const [importPreview, setImportPreview] = useState<PresetImportPreview | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [presetData, categoryData, documentData] = await Promise.all([
        listPresets(),
        listCategories(),
        listDocuments(),
      ])
      setPresets(presetData.presets)
      setCachedPresets(presetData.presets)
      setCategories(categoryData.categories)
      setDocuments(documentData.documents)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载预设任务失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const modePresets = useMemo(() => filterPresetsByMode(presets, outputMode), [outputMode, presets])
  const canReorder = filter === 'all' && !sorting

  const handleDragEnd = async (event: DragEndEvent) => {
    if (!canReorder) return
    const { active, over } = event
    if (!over) return

    const next = movePreset(modePresets, String(active.id), String(over.id))
    if (next === modePresets) return

    const previous = presets
    setSorting(true)
    setPresets([...presets.filter((preset) => preset.output_mode !== outputMode), ...next])
    try {
      const data = await reorderPresets(
        next.map((item) => item.preset_id),
        outputMode,
      )
      const merged = [
        ...previous.filter((preset) => preset.output_mode !== outputMode),
        ...data.presets,
      ]
      setPresets(merged)
      setCachedPresets(merged)
    } catch (err) {
      // 后端拒绝（如并发增删）时恢复原顺序，避免界面与服务端长期不一致
      setPresets(previous)
      setCachedPresets(previous)
      setError(err instanceof ApiError ? err.message : '保存排序失败，请刷新后重试')
    } finally {
      setSorting(false)
    }
  }

  const boundCount = modePresets.filter((preset) => isBound(preset.scope)).length
  const filterOptions = useMemo(
    () => [
      { label: `全部（${modePresets.length}）`, value: 'all' as ScopeFilter },
      { label: `未绑定（${modePresets.length - boundCount}）`, value: 'unbound' as ScopeFilter },
      { label: `指定范围（${boundCount}）`, value: 'bound' as ScopeFilter },
    ],
    [modePresets.length, boundCount],
  )
  const filteredPresets = useMemo(
    () =>
      modePresets.filter((preset) => {
        if (filter === 'unbound') return !isBound(preset.scope)
        if (filter === 'bound') return isBound(preset.scope)
        return true
      }),
    [modePresets, filter],
  )

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setFormScope(EMPTY_SCOPE)
    setFormOutputMode(outputMode)
    setModalOpen(true)
  }

  const openEdit = (preset: PresetInfo) => {
    setEditing(preset)
    form.setFieldsValue({
      title: preset.title,
      description: preset.description,
      query: preset.query,
    })
    setFormScope(preset.scope ?? EMPTY_SCOPE)
    setFormOutputMode(preset.output_mode)
    setModalOpen(true)
  }

  const closeModal = () => {
    setModalOpen(false)
    setEditing(null)
    form.resetFields()
    setFormScope(EMPTY_SCOPE)
    setFormOutputMode(outputMode)
  }

  const handleSave = async (values: PresetFormValues) => {
    setSaving(true)
    setError(null)
    // 未绑定范围时显式传 null（清空），绑定则传原始选择（类别保持动态）
    const scope = isBound(formScope) ? formScope : null
    // 「直接运行」开关已下线：统一为「卡片点击填入、按钮点击运行」，显式写 false 归一化旧数据
    const payload = { ...values, scope, auto_run: false, output_mode: formOutputMode }
    try {
      if (editing) {
        await updatePreset(editing.preset_id, payload)
        message.success(`已更新预设「${values.title}」`)
      } else {
        await createPreset(payload)
        message.success(`已新增预设「${values.title}」`)
      }
      setOutputMode(formOutputMode)
      closeModal()
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存预设失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (preset: PresetInfo) => {
    setError(null)
    try {
      await deletePreset(preset.preset_id)
      message.success(`已删除预设「${preset.title}」`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除预设失败')
    }
  }

  // --- 导入 / 导出 ---

  const handleImportFile = async (file: File) => {
    setImporting(true)
    setImportError(null)
    setImportPreview(null)
    try {
      setImportPreview(await previewPresetImport(file))
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '解析预设文件失败')
    } finally {
      setImporting(false)
    }
  }

  const handleConfirmImport = async () => {
    if (!importPreview) return
    setImporting(true)
    setImportError(null)
    try {
      const result = await confirmPresetImport(importPreview.token)
      const skipped = new Set([...importPreview.skipped_duplicates, ...result.skipped]).size
      message.success(
        `已导入 ${result.imported.length} 条预设${skipped > 0 ? `，跳过 ${skipped} 条重复` : ''}`,
      )
      setImportPreview(null)
      await refresh()
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '导入预设失败')
    } finally {
      setImporting(false)
    }
  }

  const handleExport = async () => {
    setError(null)
    try {
      const { blob, filename } = await exportPresets()
      downloadBlob(blob, filename)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '导出预设失败')
    }
  }

  const closeImport = () => {
    if (importing) return
    setImportPreview(null)
    setImportError(null)
  }

  const firstLoad = loading && presets.length === 0
  const formScopeInfo = describeScope(formScope, categories, documents)

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
          <Upload
            accept=".json"
            showUploadList={false}
            beforeUpload={(file) => {
              void handleImportFile(file)
              return false
            }}
          >
            <Button icon={<ImportOutlined />} loading={importing}>
              导入预设
            </Button>
          </Upload>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => void handleExport()}
            disabled={presets.length === 0}
          >
            导出预设
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增预设
          </Button>
        </Space>
      }
    >
      {error ? (
        <ErrorNotice
          message={error}
          onClose={() => setError(null)}
          onRetry={() => void refresh()}
        />
      ) : null}

      <Card
        title={`预设（${modePresets.length}）`}
        extra={
          <Space size={8} wrap>
            <Segmented
              value={outputMode}
              onChange={(value) => {
                setOutputMode(value as OutputMode)
                setFilter('all')
              }}
              options={[
                { label: '生成内容', value: 'generate' },
                { label: '直接输出知识库原文', value: 'verbatim' },
              ]}
            />
            {modePresets.length > 0 ? (
              <Segmented
                value={filter}
                onChange={(value) => setFilter(value as ScopeFilter)}
                options={filterOptions}
              />
            ) : null}
          </Space>
        }
      >
        {firstLoad ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : modePresets.length === 0 ? (
          <EmptyState
            title={outputMode === 'verbatim' ? '还没有原文输出预设' : '还没有生成内容预设'}
            hint={
              outputMode === 'verbatim'
                ? '新增一条原文预设：绑定单篇文档后，点卡片即可直接输出该文档原文'
                : '新增一条预设，工作台就会出现对应的一键任务'
            }
          />
        ) : filteredPresets.length === 0 ? (
          <EmptyState compact title="没有符合条件的预设" hint="切换筛选查看其它预设，或新增一条" />
        ) : (
          <>
            {filter !== 'all' ? (
              <Text type="secondary" className="preset-sort-hint">
                切换到「全部」后可拖拽排序
              </Text>
            ) : null}
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={(event) => void handleDragEnd(event)}
            >
              <SortableContext
                items={filteredPresets.map((item) => item.preset_id)}
                strategy={rectSortingStrategy}
              >
                <div className="entity-grid">
                  {filteredPresets.map((preset) => (
                    <SortablePresetCard
                      key={preset.preset_id}
                      preset={preset}
                      categories={categories}
                      documents={documents}
                      canReorder={canReorder}
                      onEdit={openEdit}
                      onDelete={(item) => void handleDelete(item)}
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          </>
        )}
      </Card>

      <Modal
        title={editing ? `编辑预设：${editing.title}` : '新增预设'}
        open={modalOpen}
        onCancel={closeModal}
        onOk={() => form.submit()}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={640}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(values) => void handleSave(values)}>
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: '请输入标题' }, { max: 40 }]}
          >
            <Input placeholder="例如：资料综述" />
          </Form.Item>
          <Form.Item
            name="description"
            label="说明"
            rules={[{ required: true, message: '请输入说明' }, { max: 120 }]}
            extra="显示在卡片上，用于说明这个预设会做什么"
          >
            <Input placeholder="例如：归纳资料中的核心主题，写成带来源引用的综述长文" />
          </Form.Item>
          <Form.Item
            name="query"
            label="任务内容"
            rules={[{ required: true, message: '请输入任务内容' }, { max: 2000 }]}
            extra="点「直接运行」时提交给 Agent 的完整任务描述"
          >
            <Input.TextArea
              autoSize={{ minRows: 4, maxRows: 10 }}
              placeholder="例如：根据我的资料，归纳其中的核心主题，写一篇带引用来源的综述文章"
            />
          </Form.Item>

          <Form.Item
            label="输出方式"
            extra="两种模式的预设相互独立：工作台切到哪个模式，就只展示该模式的预设"
          >
            <Segmented
              value={formOutputMode}
              onChange={(value) => setFormOutputMode(value as OutputMode)}
              options={[
                { label: '生成内容', value: 'generate' },
                { label: '直接输出知识库原文', value: 'verbatim' },
              ]}
            />
          </Form.Item>

          <Form.Item
            label="检索范围"
            extra={
              formOutputMode === 'verbatim'
                ? '原文预设建议绑定单篇文档：运行时直接读取该文档全文；不绑定时按任务描述自动选一篇'
                : '绑定后，在工作台点击卡片或直接运行都会套用此范围（仍可临时修改）；不绑定 = 使用工作台当前选择'
            }
          >
            <Space orientation="vertical" size="small" style={{ width: '100%' }}>
              <Space size={8} wrap>
                <Tag
                  color={
                    !formScopeInfo.bound ? 'default' : formScopeInfo.invalid ? 'orange' : 'green'
                  }
                >
                  {formScopeInfo.label}
                </Tag>
                <Button size="small" onClick={() => setScopePickerOpen(true)}>
                  选择范围
                </Button>
                {formScopeInfo.bound ? (
                  <Button size="small" type="text" onClick={() => setFormScope(EMPTY_SCOPE)}>
                    改为全部
                  </Button>
                ) : null}
              </Space>
              {formScopeInfo.invalid ? (
                <Text type="warning">
                  该范围当前没有覆盖任何文档，运行时会检索不到内容，请重新选择。
                </Text>
              ) : null}
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <ScopePicker
        open={scopePickerOpen}
        initialMode="selected"
        categories={categories}
        documents={documents}
        value={formScope}
        onCancel={() => setScopePickerOpen(false)}
        onConfirm={(selection) => {
          setFormScope(selection)
          setScopePickerOpen(false)
        }}
      />

      <ImportPreviewModal
        open={importing || importPreview !== null || importError !== null}
        title="导入预设"
        preview={importPreview}
        importing={importing}
        error={importError}
        confirmDisabled={(importPreview?.presets.length ?? 0) === 0}
        onCancel={closeImport}
        onConfirm={() => void handleConfirmImport()}
      >
        {importPreview ? (
          <>
            <Text type="secondary">
              将导入 {importPreview.presets.length} 条预设
              {importPreview.skipped_duplicates.length > 0
                ? `，跳过 ${importPreview.skipped_duplicates.length} 条重复`
                : ''}
            </Text>
            {importPreview.presets.map((item, index) => {
              const scopeInfo = describeScope(item.scope, categories, documents)
              return (
                <Card size="small" key={`${item.title}-${index}`}>
                  <Space size={8} wrap>
                    <Text strong>{item.title}</Text>
                    <Tag>{scopeInfo.bound ? `范围：${scopeInfo.label}` : '全部知识库'}</Tag>
                  </Space>
                  <Paragraph
                    type="secondary"
                    ellipsis={{ rows: 2, tooltip: item.description }}
                    style={{ marginBottom: 4 }}
                  >
                    {item.description}
                  </Paragraph>
                  <Text code ellipsis={{ tooltip: item.query }}>
                    {item.query}
                  </Text>
                </Card>
              )
            })}
            {importPreview.skipped_duplicates.length > 0 ? (
              <Text type="secondary">
                已存在相同标题与内容的预设：{importPreview.skipped_duplicates.join('、')}
              </Text>
            ) : null}
          </>
        ) : null}
      </ImportPreviewModal>
    </PageContainer>
  )
}
