import {
  ApartmentOutlined,
  KeyOutlined,
  PlusOutlined,
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
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  theme as antdTheme,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'

import EmptyState from '../components/EmptyState'
import { usePageRefresh } from '../hooks/usePageRefresh'
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

/** 团队管理：成员与对外接口密钥；仅管理员可见（后端同时校验）。 */
export default function TeamPage() {
  const { message } = App.useApp()
  const { token } = antdTheme.useToken()
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
  const [archOpen, setArchOpen] = useState(false)
  const [archMode, setArchMode] = useState<'graph' | 'matrix'>('graph')
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

  usePageRefresh(load)

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
      render: (value: string | null) =>
        value || <Typography.Text type="secondary">未绑定</Typography.Text>,
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
        <Button
          type="text"
          size="small"
          icon={<KeyOutlined />}
          onClick={() => setResetting(record)}
        >
          重置
        </Button>
      ),
    },
  ]

  const adminCount = useMemo(
    () => items.filter((item) => item.role === 'admin' && item.status === 'active').length,
    [items],
  )
  const memberCount = useMemo(
    () => items.filter((item) => item.role === 'member' && item.status === 'active').length,
    [items],
  )
  const activeKeyCount = useMemo(
    () => apiKeys.filter((key) => !key.revoked_at).length,
    [apiKeys],
  )

  const membersTab = (
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
  )

  const keysTab = (
    <Card
      variant="borderless"
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
        提交任务并取回 Markdown。密钥权限与签发成员一致，可见范围照旧生效；明文只显示一次。
      </Typography.Paragraph>
      <Table<ApiKey>
        rowKey="key_id"
        size="small"
        loading={keyLoading}
        pagination={false}
        dataSource={apiKeys}
        locale={{
          emptyText: <EmptyState title="还没有密钥" hint="新建一个，用于外部系统对接" />,
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
                <Popconfirm
                  title="吊销后该密钥立即失效"
                  onConfirm={() => void handleRevokeKey(record)}
                >
                  <Button type="link" danger size="small">
                    吊销
                  </Button>
                </Popconfirm>
              ),
          },
        ]}
      />
    </Card>
  )

  const architectureGraph = (
    <svg viewBox="0 0 720 350" width="100%" role="img" aria-label="团队架构图">
      <defs>
        <marker id="team-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" strokeWidth="1.2" />
        </marker>
      </defs>
      <g>
        <rect x="250" y="16" width="220" height="54" rx="10" fill={token.colorPrimaryBg} stroke={token.colorPrimary} strokeWidth={1} />
        <text x="360" y="38" textAnchor="middle" fill={token.colorText} fontSize="14" fontWeight={500}>团队（单团队部署）</text>
        <text x="360" y="57" textAnchor="middle" fill={token.colorTextSecondary} fontSize="12">
          管理员 {adminCount} · 成员 {memberCount} · 有效密钥 {activeKeyCount}
        </text>
      </g>
      <path d="M360 70 V108 M180 108 H540 M180 108 V134 M540 108 V134" fill="none" stroke={token.colorBorder} strokeWidth={1} markerEnd="url(#team-arrow)" />
      <g>
        <rect x="70" y="134" width="220" height="60" rx="10" fill={token.colorBgContainer} stroke={token.colorBorder} strokeWidth={1} />
        <text x="180" y="158" textAnchor="middle" fill={token.colorText} fontSize="14" fontWeight={500}>管理员</text>
        <text x="180" y="178" textAnchor="middle" fill={token.colorTextSecondary} fontSize="12">管理成员、文档与密钥</text>
      </g>
      <g>
        <rect x="430" y="134" width="220" height="60" rx="10" fill={token.colorBgContainer} stroke={token.colorBorder} strokeWidth={1} />
        <text x="540" y="158" textAnchor="middle" fill={token.colorText} fontSize="14" fontWeight={500}>成员</text>
        <text x="540" y="178" textAnchor="middle" fill={token.colorTextSecondary} fontSize="12">检索共享文档、提交任务</text>
      </g>
      <path d="M180 194 V232 M540 194 V232 M180 232 H540 M180 232 V256 M360 232 V256 M540 232 V256" fill="none" stroke={token.colorBorder} strokeWidth={1} markerEnd="url(#team-arrow)" />
      <g>
        <rect x="40" y="256" width="200" height="76" rx="10" fill={token.colorBgContainer} stroke={token.colorBorder} strokeWidth={1} />
        <text x="140" y="279" textAnchor="middle" fill={token.colorText} fontSize="13" fontWeight={500}>文档与检索</text>
        <text x="140" y="299" textAnchor="middle" fill={token.colorTextSecondary} fontSize="12">团队共享全员可见</text>
        <text x="140" y="317" textAnchor="middle" fill={token.colorTextSecondary} fontSize="12">私有仅本人与管理员</text>
      </g>
      <g>
        <rect x="260" y="256" width="200" height="76" rx="10" fill={token.colorBgContainer} stroke={token.colorBorder} strokeWidth={1} />
        <text x="360" y="279" textAnchor="middle" fill={token.colorText} fontSize="13" fontWeight={500}>任务与记忆</text>
        <text x="360" y="299" textAnchor="middle" fill={token.colorTextSecondary} fontSize="12">任务按成员隔离</text>
        <text x="360" y="317" textAnchor="middle" fill={token.colorTextSecondary} fontSize="12">偏好与长期记忆隔离</text>
      </g>
      <g>
        <rect x="480" y="256" width="200" height="76" rx="10" fill={token.colorBgContainer} stroke={token.colorBorder} strokeWidth={1} />
        <text x="580" y="279" textAnchor="middle" fill={token.colorText} fontSize="13" fontWeight={500}>对外接口</text>
        <text x="580" y="299" textAnchor="middle" fill={token.colorTextSecondary} fontSize="12">密钥继承签发成员权限</text>
        <text x="580" y="317" textAnchor="middle" fill={token.colorTextSecondary} fontSize="12">最近调用见密钥列表</text>
      </g>
    </svg>
  )

  const matrixColumns: ColumnsType<{
    ability: string
    admin: string
    member: string
    note: string
  }> = [
    { title: '能力', dataIndex: 'ability', width: 180 },
    { title: '管理员', dataIndex: 'admin', width: 90, render: (v: string) => <Tag color={v === '是' ? 'green' : 'default'}>{v}</Tag> },
    { title: '成员', dataIndex: 'member', width: 90, render: (v: string) => <Tag color={v === '是' ? 'blue' : 'default'}>{v}</Tag> },
    { title: '说明', dataIndex: 'note' },
  ]
  const matrixData = [
    { key: 'login', ability: '登录系统', admin: '是', member: '是', note: '账号密码；邮箱验证码自助重置' },
    { key: 'member-manage', ability: '管理成员', admin: '是', member: '否', note: '新增、改角色、启停用、重置密码' },
    { key: 'key-manage', ability: '签发 / 吊销密钥', admin: '是', member: '是', note: '管理员可替成员签发；成员只能管自己的' },
    { key: 'upload', ability: '上传 / 导入文档', admin: '是', member: '是', note: '导入的文档归执行导入的成员' },
    { key: 'visibility-own', ability: '改自己文档的可见范围', admin: '是', member: '是', note: '团队共享 / 仅自己' },
    { key: 'visibility-any', ability: '改任意文档的可见范围', admin: '是', member: '否', note: '非上传者返回 403' },
    { key: 'read-team', ability: '检索团队共享文档', admin: '是', member: '是', note: '全员可见' },
    { key: 'read-private', ability: '检索他人私有文档', admin: '是', member: '否', note: '检索范围冻结前按可见集合过滤' },
    { key: 'tasks', ability: '查看自己的任务历史', admin: '是', member: '是', note: '按 user_id 隔离' },
    { key: 'export', ability: '导出知识库', admin: '全部', member: '可见范围', note: 'zip 只包含导出者能看到的文档' },
  ]

  return (
    <PageContainer
      eyebrow="团队"
      title="团队管理"
      description="成员、权限与对外接口集中管理。非管理员不会看到此页面入口，后端仍二次校验。"
      extra={
        <>
          <Button icon={<ApartmentOutlined />} onClick={() => setArchOpen(true)}>
            查看架构
          </Button>
        </>
      }
    >
      <Tabs
        defaultActiveKey="members"
        items={[
          { key: 'members', label: `成员（${items.length}）`, children: membersTab },
          { key: 'keys', label: `对外接口密钥（${activeKeyCount}）`, children: keysTab },
        ]}
      />

      <Modal
        title="成员架构"
        open={archOpen}
        onCancel={() => setArchOpen(false)}
        footer={null}
        width={820}
      >
        <Segmented
          size="small"
          value={archMode}
          onChange={(value) => setArchMode(value as 'graph' | 'matrix')}
          options={[
            { label: '架构图', value: 'graph' },
            { label: '权限矩阵', value: 'matrix' },
          ]}
          style={{ marginBottom: 16 }}
        />
        {archMode === 'graph' ? architectureGraph : (
          <Table
            rowKey="key"
            size="small"
            pagination={false}
            columns={matrixColumns}
            dataSource={matrixData}
          />
        )}
        <Typography.Text type="secondary">
          架构图按当前成员与密钥实时统计；权限矩阵描述系统实际行为，与后端校验一致。
        </Typography.Text>
      </Modal>

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
