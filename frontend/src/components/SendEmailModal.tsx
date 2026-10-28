import { MailOutlined } from '@ant-design/icons'
import { Alert, App, Input, Modal, Space, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { ApiError, sendTaskEmail } from '../services/api'
import {
  isValidEmail,
  normalizeRecipient,
  readLastRecipient,
  saveLastRecipient,
} from '../utils/email'

interface SendEmailModalProps {
  open: boolean
  /** 当前要发送的任务；为空时禁用发送 */
  taskId: string | null
  /** 展示用的任务标题（通常是任务目标或用户输入） */
  title?: string | null
  onClose: () => void
}

/**
 * 把生成结果发送到邮箱。
 *
 * 只负责收集收件人并调用后端；SMTP 配置、任务完成校验与错误映射都在后端，
 * 前端不接触任何发件账号或密码。
 */
export default function SendEmailModal({ open, taskId, title, onClose }: SendEmailModalProps) {
  const { message } = App.useApp()
  const [recipient, setRecipient] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setRecipient(readLastRecipient())
    setError(null)
    setSending(false)
  }, [open])

  const valid = isValidEmail(recipient)

  const handleSend = async () => {
    if (!taskId || !valid || sending) return
    setSending(true)
    setError(null)
    try {
      const normalized = normalizeRecipient(recipient)
      const result = await sendTaskEmail(taskId, normalized)
      saveLastRecipient(normalized)
      message.success(`已发送到 ${result.to}`)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '发送失败，请稍后重试')
    } finally {
      setSending(false)
    }
  }

  return (
    <Modal
      title="发送到邮箱"
      open={open}
      onCancel={sending ? undefined : onClose}
      onOk={() => void handleSend()}
      okText="发送"
      cancelText="取消"
      confirmLoading={sending}
      okButtonProps={{ disabled: !taskId || !valid }}
      maskClosable={!sending}
      destroyOnHidden
      width={480}
    >
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        {title ? (
          <Typography.Text type="secondary" ellipsis={{ tooltip: title }}>
            文章：{title}
          </Typography.Text>
        ) : null}
        <Input
          type="email"
          placeholder="you@example.com"
          value={recipient}
          onChange={(event) => setRecipient(event.target.value)}
          onPressEnter={() => void handleSend()}
          disabled={sending}
          prefix={<MailOutlined />}
          aria-label="收件邮箱"
          autoComplete="email"
        />
        <Typography.Text type="secondary">
          邮件包含纯文本正文与 Markdown 附件（.md）。发送使用后端配置的 SMTP 服务。
        </Typography.Text>
        {!taskId ? <Alert type="warning" showIcon message="当前没有可发送的任务" /> : null}
        {error ? <Alert type="error" showIcon message={error} /> : null}
      </Space>
    </Modal>
  )
}
