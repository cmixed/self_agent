import { App, Checkbox, Input, Modal, Radio, Segmented, Select, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'

import type { DocumentCaps, DocumentInfo, GroupItem, KnowledgeBase } from '../types/api'
import { createShare } from '../services/api'
import { ApiError } from '../services/api'

const { Text, Paragraph } = Typography

/**
 * 共享知识库（或其中若干文件）。
 *
 * 能力是**组合**出来的：检索 / 列表 / 原文 / 编辑 四个开关互相级联，
 * 勾「看原文」会自动带上「列表」和「检索」，避免出现自相矛盾的组合。
 */

const PRESETS: { label: string; hint: string; caps: DocumentCaps }[] = [
  {
    label: '仅检索',
    hint: '能被 Agent 检索用于生成答案，但看不到文件列表、打不开原文',
    caps: { search: true, list: false, read: false, write: false },
  },
  {
    label: '可检索 + 看列表',
    hint: '能看到有哪些文件、多大、几个文本块，正文仍不可见',
    caps: { search: true, list: true, read: false, write: false },
  },
  {
    label: '只读',
    hint: '可检索、可列表、可在知识库页打开原文',
    caps: { search: true, list: true, read: true, write: false },
  },
  {
    label: '可编辑',
    hint: '在只读基础上还能上传、移动、删除文件',
    caps: { search: true, list: true, read: true, write: true },
  },
]

function presetOf(caps: DocumentCaps): string {
  if (caps.write) return '可编辑'
  if (caps.read) return '只读'
  if (caps.list) return '可检索 + 看列表'
  return '仅检索'
}

export default function ShareDialog({
  open,
  kb,
  documents,
  groups,
  members,
  onClose,
  onDone,
}: {
  open: boolean
  kb: KnowledgeBase | null
  documents: DocumentInfo[]
  groups: GroupItem[]
  members: { user_id: string; display_name: string }[]
  onClose: () => void
  onDone: () => void
}) {
  const { message } = App.useApp()
  const [subjectType, setSubjectType] = useState<'group' | 'user' | 'team'>('group')
  const [subjectId, setSubjectId] = useState<string>('')
  const [caps, setCaps] = useState<DocumentCaps>(PRESETS[2].caps)
  const [scope, setScope] = useState<'all' | 'subset'>('all')
  const [documentIds, setDocumentIds] = useState<string[]>([])
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)

  const subjectOptions = useMemo(() => {
    if (subjectType === 'group') {
      return groups.map((group) => ({
        value: group.group_id,
        label: `${group.name}（${group.member_count} 人）`,
      }))
    }
    if (subjectType === 'user') {
      return members.map((member) => ({ value: member.user_id, label: member.display_name }))
    }
    return []
  }, [groups, members, subjectType])

  const applyCaps = (next: Partial<DocumentCaps>) => {
    setCaps((prev) => {
      const merged = { ...prev, ...next }
      if (merged.write) return { search: true, list: true, read: true, write: true }
      if (merged.read) return { search: true, list: true, read: true, write: false }
      if (merged.list) return { search: true, list: true, read: false, write: false }
      return { search: true, list: false, read: false, write: false }
    })
  }

  const reset = () => {
    setSubjectType('group')
    setSubjectId('')
    setCaps(PRESETS[2].caps)
    setScope('all')
    setDocumentIds([])
    setReason('')
  }

  const handleSubmit = async () => {
    if (!kb) return
    if (subjectType !== 'team' && !subjectId) {
      message.warning(subjectType === 'group' ? '请选择要共享给哪个分组' : '请选择共享给哪位成员')
      return
    }
    if (scope === 'subset' && documentIds.length === 0) {
      message.warning('选择了「部分文件」时至少要勾选一个文件')
      return
    }
    setSaving(true)
    try {
      const result = await createShare(kb.kb_id, {
        subject_type: subjectType,
        subject_id: subjectType === 'team' ? '*' : subjectId,
        caps,
        document_ids: scope === 'subset' ? documentIds : [],
        reason,
      })
      if (result.status === 'active') {
        message.success('共享已生效')
      } else {
        message.success('已提交共享申请，等待管理员审批')
      }
      reset()
      onDone()
      onClose()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '创建共享失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={kb ? `共享「${kb.name}」` : '共享知识库'}
      open={open}
      onCancel={() => {
        if (saving) return
        reset()
        onClose()
      }}
      onOk={() => void handleSubmit()}
      okText="提交共享"
      cancelText="取消"
      confirmLoading={saving}
      width={600}
      destroyOnHidden
    >
      <Space direction="vertical" size={14} style={{ width: '100%' }}>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          共享是「知识库（或其中几个文件）× 一批人 × 一组能力」的组合。库主提交后立即生效；
          其他成员提交的会进入待审批，由管理员批准。
        </Paragraph>

        <div>
          <Text strong>共享给</Text>
          <div style={{ marginTop: 8 }}>
            <Segmented
              block
              value={subjectType}
              onChange={(value) => {
                setSubjectType(value as 'group' | 'user' | 'team')
                setSubjectId('')
              }}
              options={[
                { label: '分组（一批人）', value: 'group' },
                { label: '单个成员', value: 'user' },
                { label: '全团队', value: 'team' },
              ]}
            />
          </div>
          {subjectType !== 'team' ? (
            <Select
              style={{ width: '100%', marginTop: 8 }}
              placeholder={subjectType === 'group' ? '选择一个分组' : '选择一位成员'}
              value={subjectId || undefined}
              onChange={setSubjectId}
              options={subjectOptions}
              showSearch
              optionFilterProp="label"
              notFoundContent={
                subjectType === 'group'
                  ? '还没有分组，先去「团队管理 → 分组」建一个'
                  : '没有可选成员'
              }
            />
          ) : (
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              全团队包含现有和以后加入的所有成员。
            </Text>
          )}
        </div>

        <div>
          <Text strong>授予的能力</Text>
          <div style={{ marginTop: 8 }}>
            <Segmented
              block
              value={presetOf(caps)}
              onChange={(value) => {
                const preset = PRESETS.find((item) => item.label === value)
                if (preset) setCaps(preset.caps)
              }}
              options={PRESETS.map((item) => ({ label: item.label, value: item.label }))}
            />
          </div>
          <Space size={16} style={{ marginTop: 10 }} wrap>
            <Checkbox checked disabled>
              可被检索
            </Checkbox>
            <Checkbox
              checked={caps.list}
              onChange={(event) => applyCaps({ list: event.target.checked })}
            >
              可看文件列表
            </Checkbox>
            <Checkbox
              checked={caps.read}
              onChange={(event) => applyCaps({ read: event.target.checked })}
            >
              可看原文
            </Checkbox>
            <Checkbox
              checked={caps.write}
              onChange={(event) => applyCaps({ write: event.target.checked })}
            >
              可编辑（上传 / 删除）
            </Checkbox>
          </Space>
          <Text type="secondary" style={{ display: 'block', marginTop: 6 }}>
            {PRESETS.find(
              (item) =>
                item.caps.list === caps.list &&
                item.caps.read === caps.read &&
                item.caps.write === caps.write,
            )?.hint || '自定义组合：勾选后自动补齐更基础的能力'}
          </Text>
        </div>

        <div>
          <Text strong>共享范围</Text>
          <div style={{ marginTop: 8 }}>
            <Radio.Group value={scope} onChange={(event) => setScope(event.target.value)}>
              <Radio value="all">整个知识库（{documents.length} 篇）</Radio>
              <Radio value="subset">只共享其中几个文件</Radio>
            </Radio.Group>
          </div>
          {scope === 'subset' ? (
            <Select
              mode="multiple"
              style={{ width: '100%', marginTop: 8 }}
              placeholder="勾选要共享的文件"
              value={documentIds}
              onChange={setDocumentIds}
              optionFilterProp="label"
              options={documents.map((item) => ({ value: item.document_id, label: item.filename }))}
              maxTagCount="responsive"
            />
          ) : null}
        </div>

        <div>
          <Text strong>说明（会展示给审批人）</Text>
          <Input.TextArea
            style={{ marginTop: 8 }}
            rows={2}
            maxLength={200}
            showCount
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="例如：算法组的同学需要这批论文做方案对比"
          />
        </div>

        {caps.list === false ? (
          <Tag color="orange">该权限下成员看不到文件列表，只能通过任务检索到内容</Tag>
        ) : null}
      </Space>
    </Modal>
  )
}
