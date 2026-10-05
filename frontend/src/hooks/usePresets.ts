import { useEffect, useState } from 'react'

import { listPresets } from '../services/api'
import type { PresetInfo } from '../types/api'

/**
 * 工作台预设任务。
 *
 * 两个体验要点：
 * 1. 预设是**独立请求**（3-12ms），不与文档列表等慢接口绑在一起——
 *    否则会被最慢的那个拖住，出现「先空、再闪」；
 * 2. 进程内缓存 + stale-while-revalidate：来回切换页面时立即渲染上次结果，
 *    后台再刷新，不重复出现骨架屏。
 */
let cachedPresets: PresetInfo[] | null = null

export function usePresets() {
  const [presets, setPresets] = useState<PresetInfo[]>(cachedPresets ?? [])
  const [loaded, setLoaded] = useState(cachedPresets !== null)

  useEffect(() => {
    let cancelled = false
    listPresets()
      .then((data) => {
        if (cancelled) return
        cachedPresets = data.presets
        setPresets(data.presets)
        setLoaded(true)
      })
      .catch(() => {
        // 失败时保留已有缓存内容；没有缓存则落到空态，不长时间停在骨架屏
        if (!cancelled) setLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { presets, loaded }
}
