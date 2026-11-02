import { ThunderboltOutlined } from '@ant-design/icons'
import { Button, Modal, Space, Tag, Typography } from 'antd'

import type { CategoryInfo, DocumentInfo, PresetInfo } from '../types/api'
import { formatDateTime } from '../utils/format'
import { describeScope } from '../utils/scope'

const { Paragraph, Text } = Typography

interface PresetDetailModalProps {
  preset: PresetInfo | null
  categories: CategoryInfo[]
  documents: DocumentInfo[]
  running: boolean
  onClose: () => void
  onFill: (preset: PresetInfo) => void
  onRun: (preset: PresetInfo) => void
}

/**
 * 预设详情浮窗。
 *
 * 工作台卡片点击只负责填入输入框，详情在这里集中展示完整任务内容与绑定范围；
 * 「直接运行」是唯一的执行入口，避免用户想先看看内容却误触发长任务。
 */
export default function PresetDetailModal({
  preset,
  categories,
  documents,
  running,
  onClose,
  onFill,
  onRun,
}: PresetDetailModalProps) {
  if (!preset) return null

  const scope = preset.scope
  const bound = Boolean(scope && scope.category_ids.length + scope.document_ids.length > 0)
  const scopeInfo = bound && scope ? describeScope(scope, categories, documents) : null

  return (
    <Modal
      open
      title="预设详情"
      onCancel={onClose}
      width={560}
      footer={
        <Space>
          <Button onClick={onClose}>关闭</Button>
          <Button onClick={() => onFill(preset)}>填入输入框</Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            disabled={running}
            onClick={() => onRun(preset)}
          >
            直接运行
          </Button>
        </Space>
      }
    >
      <div className="preset-detail">
        <Text strong className="preset-detail__title">
          {preset.title}
        </Text>
        <Paragraph type="secondary" className="preset-detail__desc">
          {preset.description}
        </Paragraph>

        <div className="preset-detail__row">
          <Text type="secondary">输出方式</Text>
          <Tag color={preset.output_mode === 'verbatim' ? 'cyan' : 'default'}>
            {preset.output_mode === 'verbatim' ? '直接输出知识库原文' : '生成内容'}
          </Tag>
        </div>

        <div className="preset-detail__row">
          <Text type="secondary">检索范围</Text>
          {scopeInfo ? (
            <Tag color={scopeInfo.invalid ? 'orange' : 'green'}>范围：{scopeInfo.label}</Tag>
          ) : (
            <Tag>全部知识库</Tag>
          )}
        </div>

        <div className="preset-detail__field">
          <Text type="secondary">任务内容</Text>
          <div className="preset-detail__query">{preset.query}</div>
        </div>

        <Text type="secondary" className="preset-detail__meta">
          更新于 {formatDateTime(preset.updated_at)}
        </Text>
      </div>
    </Modal>
  )
}
