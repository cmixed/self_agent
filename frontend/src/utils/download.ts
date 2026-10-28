/**
 * 文件下载工具。
 *
 * 注意两个常见坑（原实现都踩了）：
 * 1. 立即调用 URL.revokeObjectURL 可能让下载被取消 -> 延迟释放
 * 2. <a> 未挂载到 DOM 时，部分浏览器不会触发下载 -> 先 append 再 click 再 remove
 */

/** 把任意文本变成安全的文件名（去掉 Windows/macOS 非法字符并限长） */
export function safeFileName(input: string, fallback = 'agent-result'): string {
  const cleaned = input
    // eslint-disable-next-line no-control-regex
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  const clipped = cleaned.slice(0, 48).trim()
  return clipped.length > 0 ? clipped : fallback
}

/** 以 Markdown 形式下载到本地 */
export function downloadMarkdown(content: string, baseName: string): void {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  downloadBlob(blob, `${safeFileName(baseName)}.md`)
}

/** 通用 Blob 下载（导出包 / 备份文件统一走这里）。 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  link.style.display = 'none'

  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)

  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
