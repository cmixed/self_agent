import {
  KeyOutlined,
  PlusOutlined,
  ReloadOutlined,
  TeamOutlined,
  UserSwitchOutlined,
} from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useState } from 'react'

import EmptyState from '../components/EmptyState'
import PageContainer from '../components/PageContainer'
import {
  createApiKey,
  createMember,
  getCachedUser,
  listApiKeys,
  listMembers,
  resetMemberPassword,
  revokeApiKey,
  updateMember,
} from '../services/auth'
import type { ApiKey, Member } from '../services/auth'

interface MemberForm {
  username: string
  display_name: string
  email?: string
  password: string
  role: string
}

/** 成员管理：单团队多成员，只对管理员可见（非管理员进入会收到 403 提示）。 */
export default function MembersPage() {
  const { message } = App.useApp()
  const [items, setItems] = useState<Member[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [resetting, setResetting] = useState<Member | null>(null)
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([])
  const [keyLoading, setKeyLoading] = useState(false)
  const [creatingKey, setCreatingKey] = useState(false)
  const [newKeyLabel, setNewKeyLabel] = useState('')
  const [plainKey, setPlainKey] = useState('')
  const [form] = Form.useForm<MemberForm>()
  const [resetForm] = Form.useForm<{ password: string }>()
  const me = getCachedUser()

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setItems(await listMembers())
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载成员失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const loadKeys = useCallback(async () => {
    setKeyLoading(true)
    try {
      setApiKeys(await listApiKeys())
    } catch {
      setApiKeys([])
    } finally {
      setKeyLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadKeys()
  }, [loadKeys])

  const handleCreateKey = async () => {
    try {
      const created = await createApiKey(newKeyLabel.trim())
      setPlainKey(created.key)
      setCreatingKey(false)
      setNewKeyLabel('')
      await loadKeys()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建密钥失败')
    }
  }

  const handleRevokeKey = async (key: ApiKey) => {
    try {
      await revokeApiKey(key.key_id)
      message.success('密钥已吊销')
      await loadKeys()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '吊销失败')
    }
  }

  const handleCreate = async (values: MemberForm) => {
    setSubmitting(true)
    try {
      await createMember({
        username: values.username.trim(),
        display_name: (values.display_name || values.username).trim(),
        email: values.email?.trim() || undefined,
        password: values.password,
        role: values.role,
      })
      message.success(`已新增成员 ${values.username}`)
      setCreating(false)
      form.resetFields()
      await load()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '新增失败')
    } finally {
      setSubmitting(false)
    }
  }

  const toggleStatus = async (member: Member, active: boolean) => {
    try {
      await updateMember(member.user_id, { status: active ? 'active' : 'disabled' })
      message.success(active ? `已启用 ${member.display_name}` : `已停用 ${member.display_name}`)
      await load()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '操作失败')
    }
  }

  const changeRole = async (member: Member, role: string) => {
    try {
      await updateMember(member.user_id, { role })
      message.success(`已设为${role === 'admin' ? '管理员' : '成员'}`)
      await load()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '操作失败')
    }
  }

  const handleResetPassword = async () => {
    if (!resetting) return
    const values = await resetForm.validateFields()
    setSubmitting(true)
    try {
      await resetMemberPassword(resetting.user_id, values.password)
      message.success(`已重置 ${resetting.display_name} 的密码`)
      setResetting(null)
      resetForm.resetFields()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '重置失败')
    } finally {
      setSubmitting(false)
    }
  }

  const columns: ColumnsType<Member> = [
    {
      title: '成员',
      dataIndex: 'display_name',
      render: (_value, record) => (
        <Space direction="vertical" size={0}>
          <Space size={6}>
            <Typography.Text strong>{record.display_name}</Typography.Text>
            {record.user_id === me?.user_id ? <Tag color="green">我</Tag> : null}
          </Space>
          <Typography.Text type="secondary">{record.username ?? '—'}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '邮箱',
      dataIndex: 'email',
      render: (value: string | null) => value || <Typography.Text type="secondary">未绑定</Typography.Text>,
    },
    {
      title: '角色',
      dataIndex: 'role',
      width: 160,
      render: (role: string, record) => (
        <Select
          size="small"
          value={role}
          style={{ width: 110 }}
          options={[
            { value: 'admin', label: '管理员' },
            { value: 'member', label: '成员' },
          ]}
          onChange={(next) => void changeRole(record, next)}
        />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (status: string, record) => (
        <Switch
          size="small"
          checked={status === 'active'}
          checkedChildren="启用"
          unCheckedChildren="停用"
          disabled={record.user_id === me?.user_id}
          onChange={(next) => void toggleStatus(record, next)}
        />
      ),
    },
    {
      title: '最近登录',
      dataIndex: 'last_login_at',
      width: 170,
      render: (value: string | null) =>
        value ? (
          value.slice(0, 16).replace('T', ' ')
        ) : (
          <Typography.Text type="secondary">从未</Typography.Text>
        ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      render: (_value, record) => (
        <Space size={4}>
          <Button
            type="text"
            size="small"
            icon={<KeyOutlined />}
            onClick={() => setResetting(record)}
          >
            重置
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <PageContainer
      eyebrow="团队"
      title="成员"
      description="同一团队共享知识库；成员可登录、检索自己有权限的文档。角色仅管理员可调整。"
      extra={
        <>
          <Button icon={<ReloadOutlined />} onClick={() => void load()} disabled={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
            新增成员
          </Button>
        </>
      }
    >
      <Card variant="borderless">
        {error ? (
          <EmptyState
            title="无法加载成员"
            hint={error}
            action={
              <Button onClick={() => void load()} icon={<UserSwitchOutlined />}>
                重试
              </Button>
            }
          />
        ) : (
          <Table<Member>
            rowKey="user_id"
            size="middle"
            loading={loading}
            columns={columns}
            dataSource={items}
            pagination={false}
            locale={{
              emptyText: (
                <EmptyState
                  title="还没有成员"
                  hint="团队至少需要一名管理员，可用右上角「新增成员」邀请。"
                  action={
                    <Button type="primary" icon={<TeamOutlined />} onClick={() => setCreating(true)}>
                      新增成员
                    </Button>
                  }
                />
              ),
            }}
          />
        )}
      </Card>

      <Card
        variant="borderless"
        style={{ marginTop: 16 }}
        title="对外接口密钥"
        extra={
          <Button icon={<PlusOutlined />} onClick={() => setCreatingKey(true)}>
            新建密钥
          </Button>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          其他系统用 <Typography.Text code>X-API-Key</Typography.Text> 调用
          <Typography.Text code> /api/v1/tasks </Typography.Text>
          提交任务并取回 Markdown。密钥权限与本成员一致，可见范围照旧生效；明文只显示一次。
        </Typography.Paragraph>
        <Table<ApiKey>
          rowKey="key_id"
          size="small"
          loading={keyLoading}
          pagination={false}
          dataSource={apiKeys}
          locale={{
            emptyText: (
              <EmptyState title="还没有密钥" hint="新建一个，用于外部系统对接" />
            ),
          }}
          columns={[
            { title: '名称', dataIndex: 'label', render: (value: string) => value || '未命名' },
            {
              title: '状态',
              dataIndex: 'revoked_at',
              width: 110,
              render: (value: string | null) => (
                <Tag color={value ? 'default' : 'green'}>{value ? '已吊销' : '有效'}</Tag>
              ),
            },
            {
              title: '创建时间',
              dataIndex: 'created_at',
              width: 170,
              render: (value: string) => value.slice(0, 16).replace('T', ' '),
            },
            {
              title: '最近调用',
              dataIndex: 'last_used_at',
              width: 170,
              render: (value: string | null) =>
                value ? value.slice(0, 16).replace('T', ' ') : '从未',
            },
            {
              title: '操作',
              key: 'actions',
              width: 90,
              render: (_value, record) =>
                record.revoked_at ? null : (
                  <Popconfirm title="吊销后该密钥立即失效" onConfirm={() => void handleRevokeKey(record)}>
                    <Button type="link" danger size="small">
                      吊销
                    </Button>
                  </Popconfirm>
                ),
            },
          ]}
        />
      </Card>

      <Modal
        title="新建密钥"
        open={creatingKey}
        onCancel={() => setCreatingKey(false)}
        onOk={() => void handleCreateKey()}
        okText="创建"
        destroyOnHidden
      >
        <Input
          placeholder="用途备注，例如：Jenkins 夜间报告"
          value={newKeyLabel}
          onChange={(event) => setNewKeyLabel(event.target.value)}
        />
      </Modal>

      <Modal
        title="密钥已创建"
        open={Boolean(plainKey)}
        onCancel={() => setPlainKey('')}
        footer={
          <Button type="primary" onClick={() => setPlainKey('')}>
            我已保存
          </Button>
        }
      >
        <Typography.Paragraph type="warning">
          此行只显示一次，关闭后无法再次查看；请立即复制保存。
        </Typography.Paragraph>
        <Typography.Paragraph code copyable={{ text: plainKey }}>
          {plainKey}
        </Typography.Paragraph>
      </Modal>

      <Modal
        title="新增成员"
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={() => form.submit()}
        okText="创建"
        confirmLoading={submitting}
        destroyOnHidden
      >
        <Form<MemberForm>
          form={form}
          layout="vertical"
          onFinish={handleCreate}
          initialValues={{ role: 'member' }}
        >
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input placeholder="登录用，创建后不可修改" autoComplete="off" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称">
            <Input placeholder="不填则与用户名相同" />
          </Form.Item>
          <Form.Item
            name="email"
            label="邮箱（用于找回密码）"
            rules={[{ type: 'email', message: '邮箱格式不正确' }]}
          >
            <Input placeholder="可选；绑定后才能自助重置密码" autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码"
            rules={[
              { required: true, message: '请输入初始密码' },
              { min: 8, message: '至少 8 位' },
            ]}
          >
            <Input.Password placeholder="至少 8 位" autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="role" label="角色">
            <Select
              options={[
                { value: 'member', label: '成员（可检索共享文档）' },
                { value: 'admin', label: '管理员（可管理成员）' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={resetting ? `重置「${resetting.display_name}」的密码` : '重置密码'}
        open={Boolean(resetting)}
        onCancel={() => {
          setResetting(null)
          resetForm.resetFields()
        }}
        onOk={() => void handleResetPassword()}
        okText="重置"
        confirmLoading={submitting}
        destroyOnHidden
      >
        <Form form={resetForm} layout="vertical">
          <Form.Item
            name="password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, message: '至少 8 位' },
            ]}
          >
            <Input.Password placeholder="至少 8 位" autoComplete="new-password" />
          </Form.Item>
          <Typography.Text type="secondary">
            重置后该成员的登录态会立即失效，需要用新密码重新登录。
          </Typography.Text>
        </Form>
      </Modal>
    </PageContainer>
  )
}
