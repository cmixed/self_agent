import { Alert, Button } from 'antd'

interface ErrorNoticeProps {
  message: string
  onClose?: () => void
  onRetry?: () => void
  retryText?: string
}

/** 统一的错误提示：可关闭、（可选）可重试；一次性提示请用 message */
export default function ErrorNotice({
  message,
  onClose,
  onRetry,
  retryText = '重试',
}: ErrorNoticeProps) {
  return (
    <Alert
      type="error"
      showIcon
      closable={onClose !== undefined}
      onClose={onClose}
      title={message}
      action={
        onRetry ? (
          <Button size="small" danger onClick={onRetry}>
            {retryText}
          </Button>
        ) : undefined
      }
    />
  )
}
