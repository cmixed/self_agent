import { useCallback, useEffect, useState } from 'react'

/**
 * 观察元素宽度（ResizeObserver）。
 *
 * 用于按顶栏实际可用空间决定展示几个任务胶囊：侧栏折叠、窗口缩放都会触发
 * 重新计算。节点延迟挂载（如窄屏切换为桌面）也能重新开始观察。
 *
 * 返回 `[ref, width]`；节点未挂载或环境不支持时为 0（由调用方回退默认值）。
 */
export function useElementWidth<T extends HTMLElement>(): [(node: T | null) => void, number] {
  const [node, setNode] = useState<T | null>(null)
  const [width, setWidth] = useState(0)

  const ref = useCallback((next: T | null) => setNode(next), [])

  useEffect(() => {
    if (!node) {
      setWidth(0)
      return
    }
    const apply = () => setWidth(node.getBoundingClientRect().width)
    apply()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(apply)
    observer.observe(node)
    return () => observer.disconnect()
  }, [node])

  return [ref, width]
}
