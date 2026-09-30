type Tone = 'success' | 'processing' | 'error' | 'warning' | 'default'

const STATUS_META: Record<string, { tone: Tone; label: string }> = {
  completed: { tone: 'success', label: '已完成' },
  running: { tone: 'processing', label: '运行中' },
  failed: { tone: 'error', label: '失败' },
  cancelled: { tone: 'warning', label: '已取消' },
}

/**
 * 统一任务状态标签：小圆点 + 文案（比彩色 Tag 更克制，适合工作台）。
 */
export default function StatusTag({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { tone: 'default' as Tone, label: status }
  return (
    <span className={`status-tag status-tag--${meta.tone}`}>
      <i className="status-tag__dot" aria-hidden="true" />
      {meta.label}
    </span>
  )
}
