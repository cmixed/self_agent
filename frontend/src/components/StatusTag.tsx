import { Badge } from 'antd'

type Tone = 'success' | 'processing' | 'error' | 'warning' | 'default'

const STATUS_META: Record<string, { tone: Tone; label: string }> = {
  completed: { tone: 'success', label: '已完成' },
  running: { tone: 'processing', label: '运行中' },
  failed: { tone: 'error', label: '失败' },
  cancelled: { tone: 'warning', label: '已取消' },
}

/**
 * 统一任务状态：antd Badge（圆点 + 文案）。
 * 比彩色 Tag 更克制，颜色走 token（success/processing/error/warning）。
 */
export default function StatusTag({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { tone: 'default' as Tone, label: status }
  return <Badge status={meta.tone} text={meta.label} />
}
