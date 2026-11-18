import { useEffect } from 'react'

/**
 * 订阅顶栏的全局刷新事件。
 *
 * 顶栏「刷新」按钮对所有数据页通用，固定在右上角；各页面通过本钩子
 * 注册自己的 refresh，避免每页各放一个按钮导致样式与位置不统一。
 */
export function usePageRefresh(refresh: () => void | Promise<void>) {
  useEffect(() => {
    const handler = () => {
      void refresh()
    }
    window.addEventListener('app:refresh', handler)
    return () => window.removeEventListener('app:refresh', handler)
  }, [refresh])
}
