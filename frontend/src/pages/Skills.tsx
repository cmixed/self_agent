import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileTextOutlined,
  ImportOutlined,
  PaperClipOutlined,
  PlusOutlined,
  ReloadOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Divider,
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Skeleton,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'

import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import PageContainer from '../components/PageContainer'
import { useViewStack } from '../components/ViewStack'
import {
  ApiError,
  confirmSkillImport,
  createSkill,
  createSkillResource,
  deleteSkill,
  deleteSkillResource,
  exportSkillPackage,
  generateSkill,
  listDocuments,
  listSkillResources,
  listSkills,
  previewSkillImport,
  updateSkill,
  updateSkillResource,
  uploadDocument,
} from '../services/api'
import type {
  DocumentInfo,
  SkillGenerateResponse,
  SkillImportPreview,
  SkillInfo,
  SkillResourceInfo,
} from '../types/api'
import { formatDateTime } from '../utils/format'

const { Text, Paragraph } = Typography

const PAGE_EYEBROW = '技能'
const PAGE_TITLE = '让 Agent 在任务中调用你的技能'
const PAGE_DESCRIPTION =
  '技能是 Agent 可调用的结构化指令：规划阶段会看到技能目录，命中时按技能说明产出分析结论，供后续写作使用。'
const PAGE_MAX_WIDTH = 1200

type SkillFilter = 'all' | 'enabled' | 'disabled'

interface SkillFormValues {
  name: string
  description: string
  content: string
}

/** 生成草稿的可编辑字段（来源由后端返回，不在这里改）。 */
type SkillDraftValues = SkillFormValues

export default function SkillsPage() {
  const { message } = App.useApp()
  const { openSkill } = useViewStack()
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<SkillFilter>('all')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<SkillInfo | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<SkillFormValues>()

  // --- 技能附件（L3）---
  const [resources, setResources] = useState<SkillResourceInfo[]>([])
  const [resourcesLoading, setResourcesLoading] = useState(false)
  const [resourceName, setResourceName] = useState('')
  const [resourceContent, setResourceContent] = useState('')
  const [editingResourceId, setEditingResourceId] = useState<string | null>(null)
  const [resourceSaving, setResourceSaving] = useState(false)

  // --- 从文档生成技能 ---
  const [genOpen, setGenOpen] = useState(false)
  const [genDocs, setGenDocs] = useState<DocumentInfo[]>([])
  const [genDocsLoading, setGenDocsLoading] = useState(false)
  const [genDocId, setGenDocId] = useState<string | null>(null)
  const [genHint, setGenHint] = useState('')
  const [genUploading, setGenUploading] = useState(false)
  const [genGenerating, setGenGenerating] = useState(false)
  const [genSaving, setGenSaving] = useState(false)
  const [genError, setGenError] = useState<string | null>(null)
  const [genResult, setGenResult] = useState<SkillGenerateResponse | null>(null)
  const [draft, setDraft] = useState<SkillDraftValues>({
    name: '',
    description: '',
    content: '',
  })

  // --- 技能包导入 / 导出 ---
  const [importOpen, setImportOpen] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importPreview, setImportPreview] = useState<SkillImportPreview | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listSkills()
      setSkills(data.skills)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载技能失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const resetResourceEditor = () => {
    setResources([])
    setResourceName('')
    setResourceContent('')
    setEditingResourceId(null)
    setResourcesLoading(false)
  }

  const loadResources = useCallback(async (skillId: string) => {
    setResourcesLoading(true)
    try {
      const data = await listSkillResources(skillId)
      setResources(data.resources)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载技能附件失败')
    } finally {
      setResourcesLoading(false)
    }
  }, [])

  const openCreate = () => {
    setEditing(null)
    resetResourceEditor()
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (skill: SkillInfo) => {
    setEditing(skill)
    resetResourceEditor()
    form.setFieldsValue({
      name: skill.name,
      description: skill.description,
      content: skill.content,
    })
    setModalOpen(true)
    void loadResources(skill.skill_id)
  }

  const closeModal = () => {
    setModalOpen(false)
    setEditing(null)
    resetResourceEditor()
    form.resetFields()
  }

  const handleSave = async (values: SkillFormValues) => {
    setSaving(true)
    setError(null)
    try {
      if (editing) {
        await updateSkill(editing.skill_id, values)
        message.success(`已更新技能「${values.name}」`)
      } else {
        await createSkill(values)
        message.success(`已创建技能「${values.name}」`)
      }
      closeModal()
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存技能失败')
    } finally {
      setSaving(false)
    }
  }

  const handleSaveResource = async () => {
    if (!editing) return
    const name = resourceName.trim()
    const content = resourceContent.trim()
    if (!name || !content) {
      setError('附件名与附件正文都不能为空')
      return
    }
    setResourceSaving(true)
    setError(null)
    try {
      if (editingResourceId) {
        await updateSkillResource(editing.skill_id, editingResourceId, { name, content })
        message.success(`已更新附件「${name}」`)
      } else {
        await createSkillResource(editing.skill_id, { name, content })
        message.success(`已添加附件「${name}」`)
      }
      setResourceName('')
      setResourceContent('')
      setEditingResourceId(null)
      await loadResources(editing.skill_id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存附件失败')
    } finally {
      setResourceSaving(false)
    }
  }

  const handleEditResource = (resource: SkillResourceInfo) => {
    setEditingResourceId(resource.resource_id)
    setResourceName(resource.name)
    setResourceContent(resource.content)
  }

  const handleDeleteResource = async (resource: SkillResourceInfo) => {
    if (!editing) return
    setError(null)
    try {
      await deleteSkillResource(editing.skill_id, resource.resource_id)
      message.success(`已删除附件「${resource.name}」`)
      if (editingResourceId === resource.resource_id) {
        setEditingResourceId(null)
        setResourceName('')
        setResourceContent('')
      }
      await loadResources(editing.skill_id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除附件失败')
    }
  }

  const handleToggle = async (skill: SkillInfo, enabled: boolean) => {
    setError(null)
    try {
      const updated = await updateSkill(skill.skill_id, { enabled })
      setSkills((prev) => prev.map((item) => (item.skill_id === updated.skill_id ? updated : item)))
      message.success(enabled ? `已启用「${skill.name}」` : `已停用「${skill.name}」`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '更新技能状态失败')
    }
  }

  const handleDelete = async (skill: SkillInfo) => {
    setError(null)
    try {
      await deleteSkill(skill.skill_id)
      message.success(`已删除技能「${skill.name}」`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除技能失败')
    }
  }

  const openGenerate = () => {
    setGenOpen(true)
    setGenDocId(null)
    setGenHint('')
    setGenResult(null)
    setGenError(null)
    setDraft({ name: '', description: '', content: '' })
    setGenDocsLoading(true)
    listDocuments()
      .then((data) => setGenDocs(data.documents))
      .catch((err) => setGenError(err instanceof ApiError ? err.message : '加载文档失败'))
      .finally(() => setGenDocsLoading(false))
  }

  const closeGenerate = () => {
    if (genGenerating || genUploading || genSaving) return
    setGenOpen(false)
    setGenResult(null)
    setGenError(null)
  }

  const handleUpload = async (file: File) => {
    setGenUploading(true)
    setGenError(null)
    try {
      const doc = await uploadDocument(file)
      setGenDocs((prev) => [doc, ...prev.filter((item) => item.document_id !== doc.document_id)])
      setGenDocId(doc.document_id)
      message.success(`已加入知识库：${doc.filename}`)
    } catch (err) {
      setGenError(err instanceof ApiError ? err.message : '上传文档失败')
    } finally {
      setGenUploading(false)
    }
  }

  const handleGenerate = async () => {
    if (!genDocId) {
      setGenError('请先选择或上传一份文档')
      return
    }
    setGenGenerating(true)
    setGenError(null)
    try {
      const result = await generateSkill({
        document_ids: [genDocId],
        hint: genHint.trim(),
      })
      setGenResult(result)
      setDraft(result.draft)
    } catch (err) {
      setGenError(err instanceof ApiError ? err.message : '生成技能失败')
    } finally {
      setGenGenerating(false)
    }
  }

  const handleSaveDraft = async () => {
    const name = draft.name.trim()
    const description = draft.description.trim()
    const content = draft.content.trim()
    if (!name || !description || !content) {
      setGenError('名称、适用场景与技能指令都不能为空')
      return
    }
    setGenSaving(true)
    setGenError(null)
    try {
      await createSkill({
        name,
        description,
        content,
        source_filename: genResult?.draft.source_filename ?? null,
      })
      message.success(`已保存技能「${name}」`)
      setGenOpen(false)
      setGenResult(null)
      setDraft({ name: '', description: '', content: '' })
      await refresh()
    } catch (err) {
      setGenError(err instanceof ApiError ? err.message : '保存技能失败')
    } finally {
      setGenSaving(false)
    }
  }

  const handleImportFile = async (file: File) => {
    setImporting(true)
    setImportError(null)
    setImportPreview(null)
    try {
      const preview = await previewSkillImport(file)
      setImportPreview(preview)
      setImportOpen(true)
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '解析技能包失败')
      setImportPreview(null)
      setImportOpen(true)
    } finally {
      setImporting(false)
    }
  }

  const handleConfirmImport = async () => {
    if (!importPreview) return
    setImporting(true)
    setImportError(null)
    try {
      const skill = await confirmSkillImport(importPreview.token)
      message.success(`已导入技能「${skill.name}」`)
      setImportOpen(false)
      setImportPreview(null)
      await refresh()
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '导入技能失败')
    } finally {
      setImporting(false)
    }
  }

  const handleExport = async (skill: SkillInfo) => {
    setError(null)
    try {
      const blob = await exportSkillPackage(skill.skill_id)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${skill.skill_id}.zip`
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      message.success(`已导出「${skill.name}」`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '导出技能包失败')
    }
  }

  const firstLoad = loading && skills.length === 0
  const enabledCount = skills.filter((skill) => skill.enabled).length
  const disabledCount = skills.length - enabledCount
  const filteredSkills = useMemo(
    () =>
      skills.filter((skill) => {
        if (filter === 'enabled') return skill.enabled
        if (filter === 'disabled') return !skill.enabled
        return true
      }),
    [skills, filter],
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
          <Upload
            accept=".zip"
            showUploadList={false}
            beforeUpload={(file) => {
              void handleImportFile(file)
              return false
            }}
          >
            <Button icon={<ImportOutlined />} loading={importing}>
              导入技能包
            </Button>
          </Upload>
          <Button icon={<FileTextOutlined />} onClick={openGenerate}>
            从文档生成
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建技能
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
        title={`技能库（${skills.length}｜启用 ${enabledCount}）`}
        extra={
          skills.length > 0 ? (
            <Segmented
              value={filter}
              onChange={(value) => setFilter(value as SkillFilter)}
              options={[
                { label: `全部（${skills.length}）`, value: 'all' },
                { label: `已启用（${enabledCount}）`, value: 'enabled' },
                { label: `已停用（${disabledCount}）`, value: 'disabled' },
              ]}
            />
          ) : null
        }
      >
        {firstLoad ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : skills.length === 0 ? (
          <EmptyState title="还没有技能" hint="新建一个技能，描述 Agent 在该场景下应当怎么做" />
        ) : filteredSkills.length === 0 ? (
          <EmptyState compact title="没有符合条件的技能" hint="切换筛选查看其它技能" />
        ) : (
          <div className="entity-grid">
            {filteredSkills.map((skill) => (
              <Card
                key={skill.skill_id}
                size="small"
                className={`entity-card entity-card--clickable${
                  skill.enabled ? '' : ' entity-card--disabled'
                }`}
                onClick={() => openSkill(skill)}
              >
                <div className="entity-card__head">
                  <Text strong className="entity-card__title" title={skill.name}>
                    {skill.name}
                  </Text>
                  <span className="entity-card__tools" onClick={(event) => event.stopPropagation()}>
                    <Tooltip
                      title={
                        skill.enabled ? '停用后不再进入 Agent 技能目录' : '启用后可被 Agent 调用'
                      }
                    >
                      <Switch
                        size="small"
                        checked={skill.enabled}
                        onChange={(checked) => void handleToggle(skill, checked)}
                      />
                    </Tooltip>
                  </span>
                </div>

                {skill.builtin || !skill.enabled || skill.source_filename ? (
                  <div className="entity-card__badges">
                    {skill.builtin ? <Tag>内置</Tag> : null}
                    {!skill.enabled ? <Tag color="default">已停用</Tag> : null}
                    {skill.source_filename ? (
                      <Tooltip title={`来源：${skill.source_filename}`}>
                        <Tag color="blue">文档生成</Tag>
                      </Tooltip>
                    ) : null}
                  </div>
                ) : null}

                <Paragraph
                  type="secondary"
                  className="entity-card__desc"
                  ellipsis={{ rows: 2, tooltip: skill.description }}
                >
                  {skill.description}
                </Paragraph>

                <Paragraph type="secondary" className="entity-card__preview" ellipsis={{ rows: 2 }}>
                  {skill.content}
                </Paragraph>

                <div className="entity-card__footer">
                  <Text type="secondary" className="entity-card__caption">
                    更新于 {formatDateTime(skill.updated_at)}
                  </Text>
                  <span onClick={(event) => event.stopPropagation()}>
                    <Space size={0}>
                      <Button
                        size="small"
                        type="text"
                        icon={<EditOutlined />}
                        aria-label="编辑"
                        onClick={() => openEdit(skill)}
                      />
                      <Tooltip title="导出标准技能包（SKILL.md + 附件）">
                        <Button
                          size="small"
                          type="text"
                          icon={<DownloadOutlined />}
                          aria-label="导出技能包"
                          onClick={() => void handleExport(skill)}
                        />
                      </Tooltip>
                      {skill.builtin ? (
                        <Tooltip title="内置技能不可删除，可编辑或停用">
                          <Button size="small" type="text" icon={<DeleteOutlined />} disabled />
                        </Tooltip>
                      ) : (
                        <Popconfirm
                          title={`删除技能「${skill.name}」？`}
                          description="删除后无法恢复"
                          okText="删除"
                          cancelText="取消"
                          onConfirm={() => void handleDelete(skill)}
                        >
                          <Button
                            size="small"
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            aria-label="删除"
                          />
                        </Popconfirm>
                      )}
                    </Space>
                  </span>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Card>

      <Modal
        title={editing ? `编辑技能：${editing.name}` : '新建技能'}
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
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入技能名称' }, { max: 60 }]}
          >
            <Input placeholder="例如：对比分析" />
          </Form.Item>
          <Form.Item
            name="description"
            label="适用场景"
            rules={[{ required: true, message: '请说明什么时候使用该技能' }, { max: 200 }]}
            extra="Planner 依据这句话判断是否调用该技能，请写清触发条件"
          >
            <Input placeholder="例如：当任务需要比较资料中的多个技术方案时使用" />
          </Form.Item>
          <Form.Item
            name="content"
            label="技能指令"
            rules={[{ required: true, message: '请输入技能指令' }]}
            extra="技能执行时作为 system 指令，指导 Agent 如何产出结论"
          >
            <Input.TextArea
              autoSize={{ minRows: 6, maxRows: 16 }}
              placeholder="你是……专家。请基于给定资料：1) …… 2) ……"
            />
          </Form.Item>
        </Form>

        <Divider />
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Space>
            <PaperClipOutlined />
            <Text strong>按需附件</Text>
          </Space>
          <Text type="secondary">
            技能目录只把附件名告诉 Agent；模型显式请求时才读取正文，最多追加一次调用。
          </Text>
          {editing ? (
            <>
              {resourcesLoading ? (
                <Skeleton active paragraph={{ rows: 1 }} title={false} />
              ) : resources.length === 0 ? (
                <Text type="secondary">还没有附件</Text>
              ) : (
                resources.map((resource) => (
                  <Card size="small" key={resource.resource_id}>
                    <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
                      <div style={{ minWidth: 0 }}>
                        <Text strong>{resource.name}</Text>
                        <Paragraph
                          type="secondary"
                          ellipsis={{ rows: 2, tooltip: resource.content }}
                          style={{ marginBottom: 0 }}
                        >
                          {resource.content}
                        </Paragraph>
                      </div>
                      <Space size={0}>
                        <Button
                          size="small"
                          type="text"
                          icon={<EditOutlined />}
                          aria-label="编辑附件"
                          onClick={() => handleEditResource(resource)}
                        />
                        <Popconfirm
                          title={`删除附件「${resource.name}」？`}
                          okText="删除"
                          cancelText="取消"
                          onConfirm={() => void handleDeleteResource(resource)}
                        >
                          <Button
                            size="small"
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            aria-label="删除附件"
                          />
                        </Popconfirm>
                      </Space>
                    </Space>
                  </Card>
                ))
              )}

              <Card size="small" title={editingResourceId ? '编辑附件' : '添加附件'}>
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Input
                    value={resourceName}
                    maxLength={260}
                    placeholder="references/checklist.md（也可只写 checklist）"
                    onChange={(event) => setResourceName(event.target.value)}
                  />
                  <Text type="secondary">
                    支持 references/、resources/、scripts/ 子目录；脚本只会保存，永远不会执行。
                  </Text>
                  <Input.TextArea
                    value={resourceContent}
                    autoSize={{ minRows: 3, maxRows: 10 }}
                    placeholder="附件正文（只有模型请求时才进入提示词）"
                    onChange={(event) => setResourceContent(event.target.value)}
                  />
                  <Space>
                    <Button
                      type="primary"
                      loading={resourceSaving}
                      onClick={() => void handleSaveResource()}
                    >
                      {editingResourceId ? '保存附件' : '添加附件'}
                    </Button>
                    {editingResourceId ? (
                      <Button
                        onClick={() => {
                          setEditingResourceId(null)
                          setResourceName('')
                          setResourceContent('')
                        }}
                      >
                        取消编辑
                      </Button>
                    ) : null}
                  </Space>
                </Space>
              </Card>
            </>
          ) : (
            <Alert type="info" showIcon message="保存技能后即可添加附件" />
          )}
        </Space>
      </Modal>

      <Modal
        title="从文档生成技能"
        open={genOpen}
        onCancel={closeGenerate}
        width={720}
        maskClosable={false}
        footer={
          genResult ? (
            <Space>
              <Button onClick={closeGenerate} disabled={genSaving}>
                取消
              </Button>
              <Button
                type="link"
                onClick={() => {
                  setGenResult(null)
                  setGenError(null)
                }}
                disabled={genSaving || genGenerating}
              >
                换一份文档
              </Button>
              <Button onClick={() => void handleGenerate()} loading={genGenerating}>
                重新生成
              </Button>
              <Button type="primary" onClick={() => void handleSaveDraft()} loading={genSaving}>
                保存为技能
              </Button>
            </Space>
          ) : (
            <Space>
              <Button onClick={closeGenerate}>取消</Button>
              <Button
                type="primary"
                loading={genGenerating}
                disabled={!genDocId}
                onClick={() => void handleGenerate()}
              >
                生成草稿
              </Button>
            </Space>
          )
        }
        destroyOnHidden
      >
        {genError ? (
          <Alert type="error" showIcon message={genError} style={{ marginBottom: 12 }} />
        ) : null}

        {genResult ? (
          <div className="skill-generate">
            {genResult.warnings.length > 0 ? (
              <Alert
                type="warning"
                showIcon
                message="生成结果有需要留意的地方"
                description={
                  <ul className="skill-generate__list">
                    {genResult.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                }
              />
            ) : null}

            {genResult.duplicate_of ? (
              <Alert
                type="info"
                showIcon
                message={`已存在同名技能「${genResult.duplicate_of.name}」`}
                description="保存会新建一个同名技能；想复用的话建议改名，或直接编辑已有技能。"
              />
            ) : null}

            <Text type="secondary">来源：{genResult.draft.source_filename ?? '（无）'}</Text>

            <label className="skill-generate__field">
              <Text type="secondary">名称</Text>
              <Input
                value={draft.name}
                maxLength={60}
                onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
              />
            </label>

            <label className="skill-generate__field">
              <Text type="secondary">适用场景</Text>
              <Input
                value={draft.description}
                maxLength={200}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, description: event.target.value }))
                }
              />
            </label>

            <label className="skill-generate__field">
              <Text type="secondary">技能指令</Text>
              <Input.TextArea
                value={draft.content}
                autoSize={{ minRows: 8, maxRows: 18 }}
                onChange={(event) => setDraft((prev) => ({ ...prev, content: event.target.value }))}
              />
            </label>
          </div>
        ) : (
          <div className="skill-generate">
            <label className="skill-generate__field">
              <Text type="secondary">选择知识库中的文档</Text>
              <Select
                showSearch
                allowClear
                style={{ width: '100%' }}
                placeholder="选择一份已索引的文档"
                loading={genDocsLoading}
                value={genDocId ?? undefined}
                onChange={(value) => setGenDocId(value ?? null)}
                optionFilterProp="label"
                options={genDocs.map((doc) => ({
                  value: doc.document_id,
                  label: `${doc.filename}（${doc.chunks} 块）`,
                }))}
              />
            </label>

            <Space wrap>
              <Upload
                accept=".md,.markdown,.txt"
                showUploadList={false}
                beforeUpload={(file) => {
                  void handleUpload(file)
                  return false
                }}
              >
                <Button icon={<UploadOutlined />} loading={genUploading}>
                  上传 .md / .txt
                </Button>
              </Upload>
              <Text type="secondary">上传的文档会加入知识库</Text>
            </Space>

            <label className="skill-generate__field">
              <Text type="secondary">额外要求（可选）</Text>
              <Input
                value={genHint}
                maxLength={200}
                placeholder="例如：偏流程化、面向工程实现"
                onChange={(event) => setGenHint(event.target.value)}
              />
            </label>

            <Alert
              type="info"
              showIcon
              message="生成只返回草稿，不会直接保存"
              description="可以先生成、检查并修改，再点「保存为技能」。"
            />
          </div>
        )}
      </Modal>
      <Modal
        title="导入技能包"
        open={importOpen}
        onCancel={() => {
          if (importing) return
          setImportOpen(false)
          setImportPreview(null)
          setImportError(null)
        }}
        width={720}
        maskClosable={false}
        footer={
          <Space>
            <Button
              onClick={() => {
                setImportOpen(false)
                setImportPreview(null)
                setImportError(null)
              }}
              disabled={importing}
            >
              取消
            </Button>
            <Button
              type="primary"
              loading={importing}
              disabled={!importPreview}
              onClick={() => void handleConfirmImport()}
            >
              确认导入
            </Button>
          </Space>
        }
        destroyOnHidden
      >
        {importError ? (
          <Alert type="error" showIcon message={importError} style={{ marginBottom: 12 }} />
        ) : null}

        {importPreview ? (
          <div className="skill-generate">
            {importPreview.warnings.length > 0 ? (
              <Alert
                type="warning"
                showIcon
                message="导入前需要留意"
                description={
                  <ul className="skill-generate__list">
                    {importPreview.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                }
              />
            ) : null}

            <Text type="secondary">
              来源：{importPreview.source_filename ?? '（未命名）'}
              {importPreview.suggested_skill_id
                ? `｜目录 ID：${importPreview.suggested_skill_id}`
                : ''}
            </Text>
            <Text type="secondary">
              {importPreview.expires_in} 秒内确认有效；导入后会保存为独立技能目录。
            </Text>

            <label className="skill-generate__field">
              <Text type="secondary">名称</Text>
              <Input value={importPreview.name} readOnly />
            </label>

            <label className="skill-generate__field">
              <Text type="secondary">适用场景</Text>
              <Input value={importPreview.description} readOnly />
            </label>

            <label className="skill-generate__field">
              <Text type="secondary">技能指令（SKILL.md 正文）</Text>
              <Input.TextArea
                value={importPreview.content}
                autoSize={{ minRows: 6, maxRows: 14 }}
                readOnly
              />
            </label>

            <Text type="secondary">附件（{importPreview.resources.length}）</Text>
            {importPreview.resources.length === 0 ? (
              <Text type="secondary">没有附件</Text>
            ) : (
              importPreview.resources.map((resource) => (
                <Card size="small" key={resource.name}>
                  <Text strong>{resource.name}</Text>
                  <Paragraph
                    type="secondary"
                    ellipsis={{ rows: 2, tooltip: resource.content }}
                    style={{ marginBottom: 0 }}
                  >
                    {resource.content}
                  </Paragraph>
                </Card>
              ))
            )}
          </div>
        ) : null}
      </Modal>
    </PageContainer>
  )
}
