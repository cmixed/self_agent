import { App as AntApp, Select, Tooltip } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, getSettings, updateLlmProvider } from '../services/api'
import type { SettingsResponse } from '../types/api'

/** Provider 显示名；未知名兜底为首字母大写。 */
export function providerLabelOf(id: string): string {
  const labels: Record<string, string> = {
    deepseek: 'DeepSeek',
    glm: 'GLM',
    ollama: 'Ollama',
  }
  return labels[id] ?? id.charAt(0).toUpperCase() + id.slice(1)
}

interface ProviderSwitchProps {
  /** 当前生效的 Provider（以 /api/health 为准）。 */
  activeProvider: string
  /** 任务执行中禁止切换，避免同一次运行混用两个模型。 */
  running: boolean
  /** 切换成功后回调（父组件刷新健康状态）。 */
  onSwitched: () => void
}

/**
 * 顶栏模型服务商切换器。
 *
 * 选项来自 GET /api/settings（含 configured 状态，未配置密钥的项禁用）；
 * 切换走 PUT /api/settings/llm-provider，失败时展示后端可读原因，
 * 受控 value 不变，自动保持原选择。
 */
export default function ProviderSwitch({ activeProvider, running, onSwitched }: ProviderSwitchProps) {
  const { message } = AntApp.useApp()
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [switching, setSwitching] = useState(false)

  useEffect(() => {
    let cancelled = false
    getSettings()
      .then((data) => {
        if (!cancelled) setSettings(data)
      })
      .catch(() => {
        if (!cancelled) setSettings(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleSwitch = useCallback(
    async (next: string) => {
      if (next === activeProvider) return
      setSwitching(true)
      try {
        await updateLlmProvider(next)
        message.success(`已切换到 ${providerLabelOf(next)}`)
        setSettings((prev) => (prev ? { ...prev, llm_provider: next } : prev))
        onSwitched()
      } catch (error) {
        const detail = error instanceof ApiError ? error.message : '切换失败，请稍后重试'
        message.error(detail)
      } finally {
        setSwitching(false)
      }
    },
    [activeProvider, message, onSwitched],
  )

  if (!settings) return null

  const options = settings.providers.map((item) => ({
    value: item.id,
    label: providerLabelOf(item.id),
    disabled: !item.configured && item.id !== settings.llm_provider,
  }))

  return (
    <Tooltip
      title={running ? '任务执行中，暂不能切换模型' : '切换模型服务商（对后续任务生效）'}
    >
      <Select
        size="small"
        className="app-header-provider"
        aria-label="切换模型服务商"
        value={activeProvider || settings.llm_provider}
        loading={switching}
        disabled={running || switching}
        onChange={(value) => void handleSwitch(value)}
        options={options}
      />
    </Tooltip>
  )
}
