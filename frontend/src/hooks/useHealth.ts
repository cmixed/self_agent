import { useCallback, useEffect, useState } from 'react'

import { getHealth } from '../services/api'
import type { HealthResponse } from '../types/api'

/** 后端健康状态（侧栏全局展示用）。 */
export function useHealth() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [loaded, setLoaded] = useState(false)

  const reload = useCallback(() => {
    getHealth()
      .then((data) => setHealth(data))
      .catch(() => setHealth(null))
      .finally(() => setLoaded(true))
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  return { health, loaded, reload }
}
