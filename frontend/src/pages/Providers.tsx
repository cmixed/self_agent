import {
  ApiOutlined,
  CheckCircleOutlined,
  CloudServerOutlined,
  DeleteOutlined,
  ExperimentOutlined,
  HddOutlined,
  PlusOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import {
  App,
  Alert,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import EmptyState from '../components/EmptyState'
import ErrorNotice from '../components/ErrorNotice'
import PageContainer from '../components/PageContainer'
import {
  ApiError,
  createProvider,
  deleteProvider,
  discoverModels,
  getSettings,
  listProviders,
  updateLlmProvider,
  testProvider,
  updateProvider,
} from '../services/api'
import type { LlmProviderOption, ProviderInfo, SettingsResponse } from '../types/api'

const { Text } = Typography

const PAGE_MAX_WIDTH = 1200

/** 常见服务商的填写模板（一键填充，减少手填错误） */
const PRESETS = [
  {
    key: 'kimi',
    label: 'Kimi（Moonshot）',
    flavor: 'openai',
    disable_thinking: false,
    base_url: 'https://api.moonshot.cn/v1',
    model: 'kimi-k3',
    api_key_env: 'MOONSHOT_API_KEY',
    requires_api_key: true,
    is_local: false,
    hint: 'OpenAI 兼容，支持 JSON 模式；官方模型列表见 /v1/models',
  },
  {
    key: 'ollama',
    label: 'Ollama（本地）',
    base_url: 'http://127.0.0.1:11434/v1',
    model: 'qwen3:4b',
    api_key_env: '',
    requires_api_key: false,
    is_local: true,
    flavor: 'ollama',
    disable_thinking: true,
    hint: '本地推理无需密钥；走原生 /api/chat 可关闭思考（快数倍）',
  },
  {
    key: 'custom',
    label: '通用 OpenAI 兼容',
    flavor: 'openai',
    disable_thinking: false,
    base_url: 'http://127.0.0.1:8080/v1',
    model: '',
    api_key_env: 'CUSTOM_API_KEY',
    requires_api_key: true,
    is_local: false,
    hint: 'vLLM / LM Studio / 任意兼容服务',
  },
] as const

interface ProviderFormValues {
  preset?: string
  flavor: string
  disable_thinking: boolean
  label: string
  base_url: string
  model: string
  api_key_env?: string
  api_key?: string
  requires_api_key: boolean
  is_local: boolean
  timeout_seconds: number
  max_retries: number
}

export default function ProvidersPage() {
  const { message } = App.useApp()
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<ProviderInfo | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [discovering, setDiscovering] = useState(false)
  const [testing, setTesting] = useState(false)
  const [form] = Form.useForm<ProviderFormValues>()
  // 观察协议选择：决定「关闭思考」是否可用（无需嵌套 render prop）
  const flavor = Form.useWatch('flavor', form)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [providerData, settingsData] = await Promise.all([listProviders(), getSettings()])
      setProviders(providerData.providers)
      setSettings(settingsData)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载模型服务失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const openCreate = () => {
    setEditing(null)
    setModels([])
    form.resetFields()
    form.setFieldsValue({
      label: '',
      base_url: '',
      model: '',
      api_key_env: '',
      api_key: '',
      requires_api_key: true,
      is_local: false,
      timeout_seconds: 120,
      max_retries: 2,
      flavor: 'openai',
      disable_thinking: false,
    })
    setModalOpen(true)
  }

  const openEdit = (provider: ProviderInfo) => {
    setEditing(provider)
    setModels([])
    form.setFieldsValue({
      label: provider.label,
      base_url: provider.base_url,
      model: provider.model,
      api_key_env: provider.api_key_env,
      api_key: '',
      requires_api_key: provider.requires_api_key,
      is_local: provider.is_local,
      timeout_seconds: provider.timeout_seconds,
      max_retries: provider.max_retries,
      flavor: provider.flavor ?? 'openai',
      disable_thinking: provider.disable_thinking ?? false,
    })
    setModalOpen(true)
  }

  const applyPreset = (key: string) => {
    const preset = PRESETS.find((item) => item.key === key)
    if (!preset) return
    form.setFieldsValue({
      label: form.getFieldValue('label') || preset.label,
      base_url: preset.base_url,
      model: preset.model,
      api_key_env: preset.api_key_env,
      requires_api_key: preset.requires_api_key,
      is_local: preset.is_local,
      timeout_seconds: preset.is_local ? 300 : 120,
      max_retries: preset.is_local ? 1 : 2,
      flavor: preset.flavor,
      disable_thinking: preset.disable_thinking,
    })
  }

  const handleDiscover = async () => {
    const baseUrl = form.getFieldValue('base_url') as string
    if (!baseUrl) {
      message.warning('请先填写接口地址')
      return
    }
    setDiscovering(true)
    try {
      const result = await discoverModels(baseUrl, editing?.provider_id)
      if (result.ok) {
        setModels(result.models)
        message.success(`发现 ${result.models.length} 个模型（${result.latency_ms} ms）`)
        if (!form.getFieldValue('model') && result.models.length > 0) {
          form.setFieldValue('model', result.models[0])
        }
      } else {
        setModels([])
        message.error(result.detail)
      }
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '获取模型列表失败')
    } finally {
      setDiscovering(false)
    }
  }

  const handleTest = async () => {
    let values: ProviderFormValues
    try {
      values = await form.validateFields(['base_url', 'model', 'requires_api_key'])
    } catch {
      return
    }
    setTesting(true)
    try {
      const result = await testProvider({
        base_url: values.base_url,
        model: values.model,
        provider_id: editing?.provider_id,
        api_key: (form.getFieldValue('api_key') as string) || undefined,
        requires_api_key: form.getFieldValue('requires_api_key') as boolean,
        is_local: form.getFieldValue('is_local') as boolean,
        timeout_seconds: Math.min(30, (form.getFieldValue('timeout_seconds') as number) || 30),
      })
      if (result.ok) {
        message.success(result.detail)
      } else {
        message.error(result.detail)
      }
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '测试连接失败')
    } finally {
      setTesting(false)
    }
  }

  const handleSave = async (values: ProviderFormValues) => {
    setSaving(true)
    setError(null)
    try {
      if (editing) {
        await updateProvider(editing.provider_id, {
          label: values.label?.trim() ? values.label : undefined,
          base_url: values.base_url,
          model: values.model,
          api_key: values.api_key ? values.api_key : undefined,
          api_key_env: values.api_key_env ?? '',
          requires_api_key: values.requires_api_key,
          is_local: values.is_local,
          timeout_seconds: values.timeout_seconds,
          max_retries: values.max_retries,
          flavor: values.flavor,
          disable_thinking: values.disable_thinking,
        })
        message.success(`已更新「${values.label}」`)
      } else {
        await createProvider({
          label: values.label?.trim() ? values.label : undefined,
          base_url: values.base_url,
          model: values.model,
          api_key: values.api_key || undefined,
          api_key_env: values.api_key_env || undefined,
          requires_api_key: values.requires_api_key,
          is_local: values.is_local,
          timeout_seconds: values.timeout_seconds,
          max_retries: values.max_retries,
          flavor: values.flavor,
          disable_thinking: values.disable_thinking,
        })
        message.success(`已添加「${values.label}」`)
      }
      setModalOpen(false)
      setEditing(null)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (provider: ProviderInfo) => {
    setError(null)
    try {
      await deleteProvider(provider.provider_id)
      message.success(`已删除「${provider.label}」`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const handleActivate = async (providerId: string) => {
    setError(null)
    try {
      await updateLlmProvider(providerId)
      message.success('已切换当前模型服务')
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '切换失败')
    }
  }

  const currentProvider = settings
    ? settings.providers.find((item: LlmProviderOption) => item.active)
    : undefined

  return (
    <PageContainer
      eyebrow="模型服务"
      title="接入你自己的模型接口"
      description="支持任意 OpenAI 兼容端点：Kimi、本地 Ollama、vLLM / LM Studio 等。密钥可用环境变量（优先）或保存在本机。"
      maxWidth={PAGE_MAX_WIDTH}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            添加模型服务
          </Button>
        </Space>
      }
    >
      {error && (
        <ErrorNotice
          message={error}
          onClose={() => setError(null)}
          onRetry={() => void refresh()}
        />
      )}

      <Alert
        type="info"
        showIcon
        message={`当前使用：${currentProvider?.label || currentProvider?.id || '—'}${
          currentProvider ? `　模型：${currentProvider.model}` : ''
        }`}
        description="切换后立即对所有新任务生效；已在执行的任务不受影响。"
      />

      <Card title={`已配置的模型服务（${(settings?.providers.length ?? 0) + 0}）`}>
        <Table<LlmProviderOption>
          rowKey="id"
          dataSource={settings?.providers ?? []}
          loading={loading}
          pagination={false}
          scroll={{ x: 'max-content' }}
          columns={[
            {
              title: '服务',
              key: 'label',
              render: (_, record) => (
                <Space size={6}>
                  {record.is_local ? <HddOutlined /> : <CloudServerOutlined />}
                  <Text strong>{record.label || record.id}</Text>
                  {record.managed ? <Tag color="blue">自定义</Tag> : <Tag>内置</Tag>}
                  {record.is_local ? <Tag color="purple">本地</Tag> : null}
                  {record.managed && record.flavor === 'ollama' ? (
                    <Tag color="cyan">原生 /api/chat</Tag>
                  ) : null}
                  {record.managed && record.disable_thinking ? (
                    <Tag color="green">关闭思考</Tag>
                  ) : null}
                </Space>
              ),
            },
            { title: '模型', dataIndex: 'model', key: 'model' },
            {
              title: '接口地址',
              dataIndex: 'base_url',
              key: 'base_url',
              render: (value: string) => <Text type="secondary">{value || '—'}</Text>,
            },
            {
              title: '密钥',
              key: 'key',
              render: (_, record) =>
                record.is_local && !record.managed ? (
                  <Tag color="default">无需密钥</Tag>
                ) : record.key_hint ? (
                  <Tooltip title={`来源：${record.key_source === 'env' ? '环境变量' : '本地保存'}`}>
                    <Tag color={record.key_source === 'env' ? 'green' : 'orange'}>
                      {record.key_hint}
                    </Tag>
                  </Tooltip>
                ) : (
                  <Tag color={record.configured ? 'default' : 'red'}>
                    {record.configured ? '无需密钥' : '未配置'}
                  </Tag>
                ),
            },
            {
              title: '状态',
              key: 'status',
              width: 160,
              render: (_, record) =>
                record.active ? (
                  <Tag icon={<CheckCircleOutlined />} color="green">
                    使用中
                  </Tag>
                ) : (
                  <Button
                    type="link"
                    disabled={!record.configured}
                    onClick={() => void handleActivate(record.id)}
                  >
                    切换到此服务
                  </Button>
                ),
            },
            {
              title: '操作',
              key: 'action',
              width: 130,
              render: (_, record) => {
                const custom = providers.find((item) => item.provider_id === record.id)
                if (!custom) return <Text type="secondary">在 .env 配置</Text>
                return (
                  <Space size={4}>
                    <Button type="link" onClick={() => openEdit(custom)}>
                      编辑
                    </Button>
                    <Popconfirm
                      title="删除该模型服务？"
                      description="删除后其配置与本地保存的密钥一并移除。"
                      onConfirm={() => void handleDelete(custom)}
                    >
                      <Button danger type="link">
                        删除
                      </Button>
                    </Popconfirm>
                  </Space>
                )
              },
            },
          ]}
        />
        {providers.length === 0 && (settings?.providers.length ?? 0) <= 2 ? (
          <EmptyState
            compact
            title="还没有自定义模型服务"
            hint="点「添加模型服务」，可直接选用 Kimi 或本地 Ollama 模板"
          />
        ) : null}
      </Card>

      <Card title="快速添加模板">
        <Space wrap>
          {PRESETS.map((preset) => (
            <Button
              key={preset.key}
              icon={preset.is_local ? <HddOutlined /> : <ApiOutlined />}
              onClick={() => {
                openCreate()
                applyPreset(preset.key)
              }}
            >
              {preset.label}
            </Button>
          ))}
        </Space>
        <div className="provider-presets__hint">
          {PRESETS.map((preset) => (
            <Text type="secondary" key={preset.key}>
              {preset.label}：{preset.hint}
            </Text>
          ))}
        </div>
      </Card>

      <Modal
        title={editing ? `编辑「${editing.label}」` : '添加模型服务'}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false)
          setEditing(null)
        }}
        onOk={() => form.submit()}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={620}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(values) => void handleSave(values)}>
          {!editing ? (
            <Form.Item name="preset" label="模板（可选，一键填充）">
              <Select
                allowClear
                placeholder="选择后自动填入地址与模型名"
                onChange={(value: string) => applyPreset(value)}
                options={PRESETS.map((preset) => ({ label: preset.label, value: preset.key }))}
              />
            </Form.Item>
          ) : null}

          <Form.Item
            name="label"
            label="名称"
            rules={[{ max: 40 }]}
            tooltip="只用于界面显示；留空则自动使用模型名"
          >
            <Input placeholder="留空则使用模型名，例如 kimi-k3 / qwen3:4b" />
          </Form.Item>

          <Form.Item
            name="base_url"
            label="接口地址（Base URL）"
            rules={[{ required: true, message: '请输入接口地址' }]}
          >
            <Input placeholder="https://api.moonshot.cn/v1 或 http://127.0.0.1:11434/v1" />
          </Form.Item>

          <Form.Item label="模型名" required>
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item name="model" noStyle rules={[{ required: true, message: '请输入模型名' }]}>
                {models.length > 0 ? (
                  <Select
                    showSearch
                    placeholder="选择或输入模型名"
                    options={models.map((item) => ({ label: item, value: item }))}
                  />
                ) : (
                  <Input placeholder="kimi-k3 / qwen3:4b" />
                )}
              </Form.Item>
              <Button
                icon={<ExperimentOutlined />}
                loading={discovering}
                onClick={() => void handleDiscover()}
              >
                发现模型
              </Button>
            </Space.Compact>
          </Form.Item>

          <Form.Item
            name="flavor"
            label="接口协议"
            tooltip="Ollama 原生协议才能关闭思考模式；其它服务保持 OpenAI 兼容 (/v1)"
          >
            <Select
              options={[
                { label: 'OpenAI 兼容（/v1/chat/completions）', value: 'openai' },
                { label: 'Ollama 原生（/api/chat）', value: 'ollama' },
              ]}
            />
          </Form.Item>

          <Form.Item
            name="disable_thinking"
            valuePropName="checked"
            label="思考模式"
            tooltip={
              flavor === 'ollama'
                ? '本地 Ollama 关闭思考可快数倍：走原生 /api/chat 并传 think=false'
                : '仅本地 Ollama（原生协议）生效；/v1 兼容层不接受 think 字段'
            }
            extra={
              flavor === 'ollama'
                ? '推荐本地小模型（如 qwen3）勾选：思考会占用大量时间与上下文'
                : '需要先选择「Ollama 原生（/api/chat）」协议（仅本地 Ollama 支持关闭思考）'
            }
          >
            <Checkbox disabled={flavor !== 'ollama'}>关闭思考（更快）</Checkbox>
          </Form.Item>

          <Space size="large" wrap>
            <Form.Item
              name="is_local"
              valuePropName="checked"
              tooltip="Ollama / LM Studio 等本机服务：不发送 Authorization 头"
            >
              <Checkbox>本地服务（无需密钥）</Checkbox>
            </Form.Item>
            <Form.Item
              name="requires_api_key"
              valuePropName="checked"
              tooltip="勾选后必须提供密钥（环境变量或下方直接填写）"
            >
              <Checkbox>需要密钥</Checkbox>
            </Form.Item>
          </Space>

          <Form.Item
            name="api_key_env"
            label="密钥所在的环境变量名（优先）"
            tooltip="填写后优先读该环境变量；backend/.env 或系统环境变量均可"
          >
            <Input placeholder="MOONSHOT_API_KEY" />
          </Form.Item>

          <Form.Item
            name="api_key"
            label={editing ? '直接填写密钥（留空 = 不修改）' : '直接填写密钥（可选）'}
            tooltip="保存在本机 SQLite，明文、仅本地使用；接口响应只回显末 4 位"
          >
            <Input.Password placeholder="sk-..." autoComplete="new-password" />
          </Form.Item>

          <Space size="large" wrap>
            <Form.Item name="timeout_seconds" label="超时（秒）">
              <InputNumber min={5} max={900} step={10} />
            </Form.Item>
            <Form.Item name="max_retries" label="最大重试">
              <InputNumber min={0} max={5} />
            </Form.Item>
          </Space>

          <Space>
            <Button
              icon={<ThunderboltOutlined />}
              loading={testing}
              onClick={() => void handleTest()}
            >
              测试连接
            </Button>
            <Button
              icon={<DeleteOutlined />}
              onClick={() => {
                setModels([])
                form.setFieldsValue({ model: '', api_key: '', api_key_env: '' })
              }}
            >
              清空填写
            </Button>
          </Space>
          <div className="provider-modal__hint">
            <Text type="secondary">
              测试连接会真实发送一条极小请求（max_tokens=8），用于确认地址、模型与密钥可用。
            </Text>
          </div>
        </Form>
      </Modal>
    </PageContainer>
  )
}
