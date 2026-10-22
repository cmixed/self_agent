import { CloudServerOutlined, HddOutlined, SettingOutlined } from '@ant-design/icons'
import { App as AntApp, Divider, Select, Space, Tooltip, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, getSettings, updateLlmProvider } from '../services/api'
import { useNav } from '../state/nav'
import type { LlmProviderOption, SettingsResponse } from '../types/api'

const { Text } = Typography

/** Provider 显示名：优先用后端给的 label（自定义 Provider 用用户起的名字）。 */
export function providerLabelOf(id: string, label?: string): string {
  if (label) return label
  const labels: Record<string, string> = {
    deepseek: 'DeepSeek',
    glm: 'GLM',
    ollama: 'Ollama（本地）',
    custom: '自定义接口',
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
 * - 选项来自 GET /api/settings（内置 + 自定义；未配置的项禁用并标注原因）；
 * - 下拉最后一项固定为「模型服务」：跳转到模型服务页添加/管理端点
 *   （Kimi / 本地 Ollama / 任意兼容端点）；
 * - 打开下拉时重新拉取：在「模型服务」页新增后无需刷新页面即可切换；
 * - 切换走 PUT /api/settings/llm-provider，失败时展示后端可读原因，受控 value 保持不变。
 */
export default function ProviderSwitch({
  activeProvider,
  running,
  onSwitched,
}: ProviderSwitchProps) {
  const { message } = AntApp.useApp()
  const { navigate } = useNav()
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [switching, setSwitching] = useState(false)

  const load = useCallback(async () => {
    try {
      setSettings(await getSettings())
    } catch {
      setSettings(null)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

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

  // 本地模型服务排在前面，云端在后；同组内保持后端顺序
  const ordered = [
    ...settings.providers.filter((item: LlmProviderOption) => item.is_local),
    ...settings.providers.filter((item: LlmProviderOption) => !item.is_local),
  ]

  const options = ordered.map((item: LlmProviderOption) => {
    const unconfigured = !item.configured && item.id !== settings.llm_provider
    // 展示「图标 + 模型名」：本地用硬盘图标，云端用服务图标
    const name = item.model || providerLabelOf(item.id, item.label)
    return {
      value: item.id,
      label: (
        <Space size={6}>
          {item.is_local ? <HddOutlined /> : <CloudServerOutlined />}
          <span>{name}</span>
          {unconfigured ? <Text type="secondary">未配置</Text> : null}
        </Space>
      ),
      disabled: unconfigured,
    }
  })

  return (
    <Tooltip title={running ? '任务执行中，暂不能切换模型' : '切换模型服务商（对后续任务生效）'}>
      <Select
        size="small"
        className="app-header-provider"
        aria-label="切换模型服务商"
        value={activeProvider || settings.llm_provider}
        loading={switching}
        disabled={running || switching}
        onOpenChange={(open) => {
          // 在「模型服务」页刚添加的 Provider 需要立刻可切换：打开时重新拉取
          if (open) void load()
        }}
        onChange={(value) => void handleSwitch(value)}
        options={options}
        popupRender={(menu) => (
          <>
            {menu}
            <Divider style={{ margin: '4px 0' }} />
            <button
              type="button"
              className="app-header-provider__manage"
              onClick={() => navigate('providers')}
            >
              <SettingOutlined /> 模型服务
            </button>
          </>
        )}
      />
    </Tooltip>
  )
}
