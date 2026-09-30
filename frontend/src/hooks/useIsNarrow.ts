import { useEffect, useState } from 'react'

/**
 * 是否处于窄屏（< 992px）。
 * 窄屏下侧栏改为抽屉，由顶栏汉堡按钮唤出。
 */
export function useIsNarrow(query = '(max-width: 991px)') {
  const [narrow, setNarrow] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    const mq = window.matchMedia(query)
    const apply = () => setNarrow(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [query])

  return narrow
}
