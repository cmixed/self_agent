import { Alert, Button, Modal, Space, Typography } from 'antd'
import type { ReactNode } from 'react'

const { Text } = Typography

export interface ImportPreviewMeta {
  warnings: string[]
  source_filename?: string | null
  /** 预览 token 的有效期（秒） */
  expires_in: number
}

interface ImportPreviewModalProps {
  open: boolean
  title: string
  preview: ImportPreviewMeta | null
  importing: boolean
  error: string | null
  /** 预览为空（例如全部重复）时禁用确认 */
  confirmDisabled?: boolean
  onCancel: () => void
  onConfirm: () => void
  /** 各域自己的预览详情列表 */
  children?: ReactNode
}

/**
 * 系统统一的导入预览弹窗。
 *
 * 预设 / 长期记忆 / 知识库 / 技能包都复用同一形态：
 * 先看警告与将导入的内容，再点确认落盘；确认按钮在导入中不可重复点击。
 */
export default function ImportPreviewModal({
  open,
  title,
  preview,
  importing,
  error,
  confirmDisabled = false,
  onCancel,
  onConfirm,
  children,
}: ImportPreviewModalProps) {
  return (
    <Modal
      title={title}
      open={open}
      onCancel={() => {
        if (!importing) onCancel()
      }}
      width={760}
      maskClosable={false}
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={onCancel} disabled={importing}>
            取消
          </Button>
          <Button
            type="primary"
            loading={importing}
            disabled={!preview || confirmDisabled}
            onClick={onConfirm}
          >
            确认导入
          </Button>
        </Space>
      }
    >
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!preview && !error && importing ? <Text type="secondary">正在解析文件…</Text> : null}

      {preview ? (
        <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
          {preview.warnings.length > 0 ? (
            <Alert
              type="warning"
              showIcon
              message="导入前需要留意"
              description={
                <ul className="skill-generate__list">
                  {preview.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              }
            />
          ) : null}
          <Text type="secondary">
            来源：{preview.source_filename ?? '（未命名）'}｜{preview.expires_in} 秒内确认有效
          </Text>
          {children}
        </Space>
      ) : null}
    </Modal>
  )
}
