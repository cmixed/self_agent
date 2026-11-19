import {
  ApartmentOutlined,
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
  EditOutlined,
  KeyOutlined,
  PlusOutlined,
  SafetyOutlined,
  ShareAltOutlined,
  TeamOutlined,
  UserAddOutlined,
  UserSwitchOutlined,
  UsergroupAddOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Menu,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'

import EmptyState from '../components/EmptyState'
import PageContainer from '../components/PageContainer'
import ShareGraph from '../components/ShareGraph'
import { usePageRefresh } from '../hooks/usePageRefresh'
import {
  addGroupMember,
  createGroup,
  decideGroupMember,
  decideShare,
  deleteGroup,
  getShareGraph,
  joinGroup,
  listGroups,
  listShares,
  removeGroupMember,
  revokeShare,
  setGroupMemberRole,
  updateGroup,
} from '../services/api'
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
import type { GroupItem, GroupMember, ShareGraphData, ShareItem } from '../types/api'

const { Text, Paragraph } = Typography

interface MemberForm {
  username: string
  display_name: string
  email?: string
  password: string
  role: string
}

interface GroupForm {
  name: string
  description?: string
}

const ROLE_META: Record<string, { label: string; color: string }> = {
  manager: { label: '组内编辑者', color: 'purple' },
  member: { label: '组内成员', color: 'blue' },
  pending: { label: '待审批', color: 'orange' },
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  active: { label: '已生效', color: 'green' },
  pending: { label: '待审批', color: 'orange' },
  rejected: { label: '已驳回', color: 'default' },
}

const SUBJECT_META: Record<string, { label: string; color: string }> = {
  team: { label: '全团队', color: 'blue' },
  group: { label: '分组', color: 'geekblue' },
  user: { label: '成员', color: 'default' },
}

/**
 * 团队管理：成员、分组、共享审批与关系图。
 *
 * 权限模型是**组合**而不是角色继承：四项目录能力（检索 / 列表 / 原文 / 编辑）
 * 由命中的共享记录取并集推出，分组只作为「一批人」的授予对象。
 */
export default function TeamPage() {
  const { message } = App.useApp()
  const me = getCachedUser()

  const [tab, setTab] = useState('members')

  const [items, setItems] = useState<Member[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [resetting, setResetting] = useState<Member | null>(null)

  const [groups, setGroups] = useState<GroupItem[]>([])
  const [groupLoading, setGroupLoading] = useState(false)
  const [groupModalOpen, setGroupModalOpen] = useState(false)
  const [editingGroup, setEditingGroup] = useState<GroupItem | null>(null)
  const [groupForm] = Form.useForm<GroupForm>()
  const [addTarget, setAddTarget] = useState<GroupItem | null>(null)
  const [addUserId, setAddUserId] = useState('')
  const [addRole, setAddRole] = useState<'manager' | 'member'>('member')

  const [shares, setShares] = useState<ShareItem[]>([])
  const [shareLoading, setShareLoading] = useState(false)
  const [shareView, setShareView] = useState<'pending' | 'all'>('pending')

  const [graph, setGraph] = useState<ShareGraphData | null>(null)
  const [graphLoading, setGraphLoading] = useState(false)

  const [apiKeys, setApiKeys] = useState<ApiKey[]>([])
  const [keyLoading, setKeyLoading] = useState(false)
  const [creatingKey, setCreatingKey] = useState(false)
  const [newKeyLabel, setNewKeyLabel] = useState('')
  const [plainKey, setPlainKey] = useState('')
  const [busyKey, setBusyKey] = useState('')

  const [form] = Form.useForm<MemberForm>()
  const [resetForm] = Form.useForm<{ password: string }>()

  // --- 加载 ---

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

  const loadGroups = useCallback(async () => {
    setGroupLoading(true)
    try {
      setGroups((await listGroups()).items)
    } catch {
      setGroups([])
    } finally {
      setGroupLoading(false)
    }
  }, [])

  const loadShares = useCallback(async (view: 'pending' | 'all') => {
    setShareLoading(true)
    try {
      setShares((await listShares(view)).items)
    } catch {
      setShares([])
    } finally {
      setShareLoading(false)
    }
  }, [])

  const loadGraph = useCallback(async () => {
    setGraphLoading(true)
    try {
      setGraph(await getShareGraph())
    } catch {
      setGraph(null)
    } finally {
      setGraphLoading(false)
    }
  }, [])

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

  const reloadAll = useCallback(() => {
    void load()
    void loadGroups()
    void loadShares(shareView)
    void loadKeys()
  }, [load, loadGroups, loadShares, loadKeys, shareView])

  usePageRefresh(reloadAll)

  useEffect(() => {
    void load()
    void loadGroups()
    void loadKeys()
  }, [load, loadGroups, loadKeys])

  useEffect(() => {
    void loadShares(shareView)
  }, [loadShares, shareView])

  useEffect(() => {
    if (tab !== 'graph') return
    void loadGraph()
  }, [tab, loadGraph])

  // --- 成员操作 ---

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

  // --- 密钥操作 ---

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

  // --- 分组操作 ---

  const openCreateGroup = () => {
    setEditingGroup(null)
    groupForm.resetFields()
    setGroupModalOpen(true)
  }

  const openEditGroup = (group: GroupItem) => {
    setEditingGroup(group)
    groupForm.setFieldsValue({ name: group.name, description: group.description })
    setGroupModalOpen(true)
  }

  const handleSaveGroup = async (values: GroupForm) => {
    setSubmitting(true)
    try {
      if (editingGroup) {
        await updateGroup(editingGroup.group_id, values)
        message.success(`已更新分组「${values.name}」`)
      } else {
        await createGroup(values.name.trim(), values.description?.trim() ?? '')
        message.success(`已创建分组「${values.name}」，你是组内编辑者`)
      }
      setGroupModalOpen(false)
      setEditingGroup(null)
      groupForm.resetFields()
      await loadGroups()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存分组失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteGroup = async (group: GroupItem) => {
    try {
      await deleteGroup(group.group_id)
      message.success(`已删除分组「${group.name}」，指向它的共享已一并收回`)
      await loadGroups()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除分组失败')
    }
  }

  const handleJoin = async (group: GroupItem) => {
    setBusyKey(`join-${group.group_id}`)
    try {
      await joinGroup(group.group_id)
      message.success(`已提交加入「${group.name}」的申请`)
      await loadGroups()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '申请失败')
    } finally {
      setBusyKey('')
    }
  }

  const handleDecideMember = async (group: GroupItem, userId: string, approve: boolean) => {
    setBusyKey(`decide-${group.group_id}-${userId}`)
    try {
      await decideGroupMember(group.group_id, userId, approve)
      message.success(approve ? '已同意加入' : '已拒绝申请')
      await loadGroups()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '审批失败')
    } finally {
      setBusyKey('')
    }
  }

  const handleAddMember = async () => {
    if (!addTarget || !addUserId) {
      message.warning('请选择要拉入的成员')
      return
    }
    setSubmitting(true)
    try {
      await addGroupMember(addTarget.group_id, addUserId, addRole)
      message.success('已拉入分组')
      setAddTarget(null)
      setAddUserId('')
      await loadGroups()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '拉人失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleMemberRole = async (group: GroupItem, userId: string, role: 'manager' | 'member') => {
    try {
      await setGroupMemberRole(group.group_id, userId, role)
      message.success('已调整组内角色')
      await loadGroups()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '调整角色失败')
    }
  }

  const handleRemoveMember = async (group: GroupItem, userId: string) => {
    try {
      await removeGroupMember(group.group_id, userId)
      message.success('已移出分组')
      await loadGroups()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '移出失败')
    }
  }

  // --- 共享审批 ---

  const handleDecideShare = async (share: ShareItem, approve: boolean) => {
    setBusyKey(`share-${share.share_id}`)
    try {
      await decideShare(share.share_id, approve)
      message.success(approve ? '已批准该共享' : '已驳回该共享')
      await Promise.all([loadShares(shareView), loadGraph()])
    } catch (err) {
      message.error(err instanceof Error ? err.message : '审批失败')
    } finally {
      setBusyKey('')
    }
  }

  const handleRevokeShare = async (share: ShareItem) => {
    setBusyKey(`share-${share.share_id}`)
    try {
      await revokeShare(share.share_id)
      message.success('已撤销该共享')
      await Promise.all([loadShares(shareView), loadGraph()])
    } catch (err) {
      message.error(err instanceof Error ? err.message : '撤销失败')
    } finally {
      setBusyKey('')
    }
  }

  // --- 派生 ---

  const adminCount = useMemo(
    () => items.filter((item) => item.role === 'admin' && item.status === 'active').length,
    [items],
  )
  const memberCount = useMemo(
    () => items.filter((item) => item.role === 'member' && item.status === 'active').length,
    [items],
  )
  const activeKeyCount = useMemo(() => apiKeys.filter((key) => !key.revoked_at).length, [apiKeys])
  const pendingShareCount = useMemo(
    () => shares.filter((item) => item.status === 'pending').length,
    [shares],
  )
  const pendingMemberCount = useMemo(
    () => groups.reduce((sum, group) => sum + group.pending_count, 0),
    [groups],
  )

  // --- 成员表 ---

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
      width: 132,
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
      width: 96,
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
      title: '所在分组',
      key: 'groups',
      width: 160,
      render: (_value, record) => {
        const mine = groups.filter((group) =>
          group.members?.some(
            (member) => member.user_id === record.user_id && member.status === 'active',
          ),
        )
        if (mine.length === 0) return <Text type="secondary">—</Text>
        return (
          <Space size={[4, 4]} wrap>
            {mine.map((group) => (
              <Tag key={group.group_id} className="kb-tag">
                {group.name}
              </Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '最近登录',
      dataIndex: 'last_login_at',
      width: 132,
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
      width: 92,
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
          /* max-content：列按内容撑开，窄屏横向滚动。
             不要改成固定值——无宽度的「成员 / 邮箱」列会被压成一字一行 */
          scroll={{ x: 'max-content' }}
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

  // --- 分组 ---

  const renderGroupMembers = (group: GroupItem) => {
    if (group.members.length === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="成员名单不可见：你不是这个分组的成员"
        />
      )
    }
    const memberColumns: ColumnsType<GroupMember> = [
      {
        title: '成员',
        dataIndex: 'display_name',
        render: (value: string, record) => (
          <Space size={6}>
            <Text strong>{value}</Text>
            {record.user_id === me?.user_id ? <Tag color="green">我</Tag> : null}
          </Space>
        ),
      },
      {
        title: '组内角色',
        dataIndex: 'role',
        width: 190,
        render: (role: string, record) =>
          record.status === 'pending' ? (
            <Text type="secondary">—</Text>
          ) : group.can_manage ? (
            <Select
              size="small"
              value={role}
              style={{ width: 168 }}
              options={[
                { value: 'manager', label: '编辑者（可审批）' },
                { value: 'member', label: '成员' },
              ]}
              onChange={(next) =>
                void handleMemberRole(group, record.user_id, next as 'manager' | 'member')
              }
            />
          ) : (
            <Tag color={ROLE_META[role]?.color}>{ROLE_META[role]?.label ?? role}</Tag>
          ),
      },
      {
        title: '状态',
        dataIndex: 'status',
        width: 100,
        render: (status: string) => (
          <Tag color={status === 'pending' ? 'orange' : 'green'}>
            {status === 'pending' ? '待审批' : '在组内'}
          </Tag>
        ),
      },
      {
        title: '加入时间',
        dataIndex: 'joined_at',
        width: 160,
        render: (value: string) => value.slice(0, 16).replace('T', ' '),
      },
      {
        title: '操作',
        key: 'actions',
        width: 170,
        render: (_value, record) => {
          if (!group.can_manage && record.user_id !== me?.user_id) return null
          if (record.status === 'pending') {
            return (
              <Space size={2}>
                <Button
                  type="link"
                  size="small"
                  icon={<CheckOutlined />}
                  loading={busyKey === `decide-${group.group_id}-${record.user_id}`}
                  onClick={() => void handleDecideMember(group, record.user_id, true)}
                >
                  同意
                </Button>
                <Button
                  type="link"
                  size="small"
                  danger
                  icon={<CloseOutlined />}
                  onClick={() => void handleDecideMember(group, record.user_id, false)}
                >
                  拒绝
                </Button>
              </Space>
            )
          }
          if (record.user_id === me?.user_id && !group.can_manage) {
            return (
              <Popconfirm
                title="退出这个分组？"
                description="退出后会失去该分组带来的共享能力。"
                onConfirm={() => void handleRemoveMember(group, record.user_id)}
              >
                <Button type="link" size="small" danger>
                  退出
                </Button>
              </Popconfirm>
            )
          }
          return (
            <Popconfirm
              title="移出分组？"
              description="该成员会立即失去这个分组带来的共享能力。"
              onConfirm={() => void handleRemoveMember(group, record.user_id)}
            >
              <Button type="link" size="small" danger>
                移出
              </Button>
            </Popconfirm>
          )
        },
      },
    ]
    return (
      <Table<GroupMember>
        rowKey="user_id"
        size="small"
        pagination={false}
        dataSource={group.members}
        columns={memberColumns}
      />
    )
  }

  const groupColumns: ColumnsType<GroupItem> = [
    {
      title: '分组',
      dataIndex: 'name',
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Space size={6}>
            <Text strong>{value}</Text>
            {record.my_role ? (
              <Tag color={ROLE_META[record.my_role]?.color}>
                {ROLE_META[record.my_role]?.label ?? record.my_role}
              </Tag>
            ) : null}
            {record.pending_count > 0 ? (
              <Tag color="orange">{record.pending_count} 待审批</Tag>
            ) : null}
          </Space>
          <Text type="secondary">
            {record.description || '（无说明）'} · {record.created_by_name} 建
          </Text>
        </Space>
      ),
    },
    {
      title: '人数',
      dataIndex: 'member_count',
      width: 80,
    },
    {
      title: '操作',
      key: 'actions',
      width: 260,
      render: (_value, record) => (
        <Space size={2} wrap>
          {!record.my_role ? (
            <Button
              type="link"
              size="small"
              icon={<UserAddOutlined />}
              loading={busyKey === `join-${record.group_id}`}
              onClick={() => void handleJoin(record)}
            >
              申请加入
            </Button>
          ) : null}
          {record.can_manage ? (
            <>
              <Button
                type="link"
                size="small"
                icon={<UsergroupAddOutlined />}
                onClick={() => {
                  setAddTarget(record)
                  setAddUserId('')
                  setAddRole('member')
                }}
              >
                拉人
              </Button>
              <Button
                type="link"
                size="small"
                icon={<EditOutlined />}
                onClick={() => openEditGroup(record)}
              >
                编辑
              </Button>
              <Popconfirm
                title={`删除分组「${record.name}」？`}
                description="指向该分组的共享会一并收回，组内成员将失去这些能力。"
                onConfirm={() => void handleDeleteGroup(record)}
              >
                <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            </>
          ) : null}
        </Space>
      ),
    },
  ]

  const groupsTab = (
    <Card
      variant="borderless"
      title="分组（「一批人」的载体）"
      extra={
        <Button icon={<PlusOutlined />} onClick={openCreateGroup}>
          新建分组
        </Button>
      }
    >
      <Paragraph type="secondary" style={{ marginTop: 0 }}>
        分组本身不带任何权限，只是共享的授予对象。建组人自动成为组内编辑者：编辑者可以直接拉人、
        审批入组申请（默认路径）；管理员可以建组、拉人、审批，也可以改任何分组。
      </Paragraph>
      <Table<GroupItem>
        rowKey="group_id"
        size="middle"
        loading={groupLoading}
        dataSource={groups}
        pagination={false}
        columns={groupColumns}
        scroll={{ x: 'max-content' }}
        expandable={{ expandedRowRender: renderGroupMembers }}
        locale={{
          emptyText: (
            <EmptyState
              title="还没有分组"
              hint="把需要同一批资料的同事放进一个分组，再把知识库共享给它"
              action={
                <Button type="primary" icon={<PlusOutlined />} onClick={openCreateGroup}>
                  新建分组
                </Button>
              }
            />
          ),
        }}
      />
    </Card>
  )

  // --- 共享与审批 ---

  const shareColumns: ColumnsType<ShareItem> = [
    {
      title: '知识库',
      dataIndex: 'kb_name',
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary">
            {record.document_ids.length > 0
              ? `仅 ${record.document_ids.length} 个文件`
              : '整个知识库'}
          </Text>
        </Space>
      ),
    },
    {
      title: '共享给',
      dataIndex: 'subject_name',
      render: (value: string, record) => (
        <Space size={6} wrap>
          <Tag color={SUBJECT_META[record.subject_type]?.color}>
            {SUBJECT_META[record.subject_type]?.label}
          </Tag>
          {record.subject_type === 'team' ? null : <Text>{value}</Text>}
        </Space>
      ),
    },
    {
      title: '授予能力',
      dataIndex: 'caps_label',
      width: 140,
      render: (value: string) => <Tag className="kb-tag">{value}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) => (
        <Tag color={STATUS_META[value]?.color}>{STATUS_META[value]?.label ?? value}</Tag>
      ),
    },
    {
      title: '申请人 / 说明',
      key: 'reason',
      render: (_value, record) => (
        <Space direction="vertical" size={0}>
          <Text>{record.requested_by_name}</Text>
          <Text type="secondary">{record.reason || '（未填写说明）'}</Text>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 190,
      render: (_value, record) => {
        if (record.status === 'pending') {
          return (
            <Space size={2}>
              <Button
                type="link"
                size="small"
                icon={<CheckOutlined />}
                loading={busyKey === `share-${record.share_id}`}
                onClick={() => void handleDecideShare(record, true)}
              >
                批准
              </Button>
              <Button
                type="link"
                size="small"
                danger
                icon={<CloseOutlined />}
                onClick={() => void handleDecideShare(record, false)}
              >
                驳回
              </Button>
            </Space>
          )
        }
        if (record.status === 'rejected') return <Text type="secondary">已驳回</Text>
        return (
          <Popconfirm
            title="撤销该共享？"
            description="该主体会立即失去这条记录带来的能力（其他共享仍然生效）。"
            onConfirm={() => void handleRevokeShare(record)}
          >
            <Button
              type="link"
              size="small"
              danger
              loading={busyKey === `share-${record.share_id}`}
            >
              撤销
            </Button>
          </Popconfirm>
        )
      },
    },
  ]

  const capsExplain = (
    <Card size="small" title="权限是怎么组合出来的" className="kb-caps-explain">
      <div className="kb-caps-explain__grid">
        <div>
          <Tag color="gold">仅检索</Tag>
          <Text type="secondary">Agent 能检索到内容并引用，但看不到文件列表、打不开原文</Text>
        </div>
        <div>
          <Tag color="blue">可检索 + 看列表</Tag>
          <Text type="secondary">能看到有哪些文件、多大、几个文本块，正文仍然不可见</Text>
        </div>
        <div>
          <Tag color="green">只读</Tag>
          <Text type="secondary">可检索、可列表、可在知识库页打开原文</Text>
        </div>
        <div>
          <Tag color="purple">可编辑</Tag>
          <Text type="secondary">在只读基础上还能上传、移动、删除文件</Text>
        </div>
      </div>
      <Paragraph type="secondary" style={{ margin: '10px 0 0' }}>
        同一个人可能通过多个分组或多条记录获得能力，最终按<Text strong>并集</Text>
        生效；撤销一条只收回这条记录
        带来的能力。管理员能看到全部关系（谁把哪个库共享给了谁），但看不到库里的内容——内容访问仍按能力判定。
      </Paragraph>
    </Card>
  )

  const sharesTab = (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card
        variant="borderless"
        title="共享与审批"
        extra={
          <Segmented
            size="small"
            value={shareView}
            onChange={(value) => setShareView(value as 'pending' | 'all')}
            options={[
              {
                label: `待审批${pendingShareCount > 0 ? `（${pendingShareCount}）` : ''}`,
                value: 'pending',
              },
              { label: '全部关系', value: 'all' },
            ]}
          />
        }
      >
        {shareView === 'pending' ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="成员把「自己的知识库」共享给分组时需要管理员批准"
            description="库主共享自己的库、管理员发起的共享会直接生效；其余情况进入这里等待处理。"
          />
        ) : null}
        <Table<ShareItem>
          rowKey="share_id"
          size="middle"
          loading={shareLoading}
          dataSource={shares}
          pagination={shares.length > 10 ? { pageSize: 10 } : false}
          columns={shareColumns}
          scroll={{ x: 'max-content' }}
          locale={{
            emptyText: (
              <EmptyState
                title={shareView === 'pending' ? '没有待审批的共享' : '还没有任何共享关系'}
                hint={
                  shareView === 'pending'
                    ? '成员提交「库 → 分组」的共享申请后会出现在这里'
                    : '在知识库页把库（或其中几个文件）共享给分组，就会产生关系'
                }
              />
            ),
          }}
        />
      </Card>
      {capsExplain}
    </Space>
  )

  // --- 关系图 ---

  const graphTab = (
    <Card
      variant="borderless"
      title="共享关系图"
      extra={
        <Space size={8}>
          <Text type="secondary">
            {graph ? `${graph.nodes.length} 个节点 · ${graph.edges.length} 条关系` : ''}
          </Text>
          {graph && graph.pending_count > 0 ? (
            <Tag color="orange">{graph.pending_count} 条待审批</Tag>
          ) : null}
          <Button size="small" onClick={() => void loadGraph()} loading={graphLoading}>
            刷新
          </Button>
        </Space>
      }
    >
      <Paragraph type="secondary" style={{ marginTop: 0 }}>
        成员 → 分组 → 知识库。实线是已生效的共享，虚线是等待审批的申请；箭头颜色表示授予的能力。
        管理员能看到全部关系，但看不到库里的内容。
      </Paragraph>
      <ShareGraph graph={graph} loading={graphLoading} />
    </Card>
  )

  // --- 密钥 ---

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
        提交任务并取回
        Markdown。密钥权限与签发成员一致，检索范围按该成员的能力集合判定；明文只显示一次。
      </Typography.Paragraph>
      <Table<ApiKey>
        rowKey="key_id"
        size="small"
        loading={keyLoading}
        pagination={false}
        dataSource={apiKeys}
        scroll={{ x: 'max-content' }}
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

  const memberOptions = items
    .filter((item) => item.status === 'active')
    .map((item) => ({ value: item.user_id, label: item.display_name }))

  // 五个板块改成左栏的二级导航，右侧直接渲染当前板块，不再用横向 Tabs
  const tabItems = [
    {
      key: 'members',
      label: `成员（${items.length}）`,
      icon: <TeamOutlined />,
      children: membersTab,
    },
    {
      key: 'groups',
      label: `分组（${groups.length}）`,
      icon: <ApartmentOutlined />,
      children: groupsTab,
    },
    {
      key: 'shares',
      label: `共享与审批${pendingShareCount > 0 ? `（${pendingShareCount}）` : ''}`,
      icon: <SafetyOutlined />,
      children: sharesTab,
    },
    {
      key: 'graph',
      label: '共享关系图',
      icon: <ShareAltOutlined />,
      children: graphTab,
    },
    {
      key: 'keys',
      label: `对外接口密钥（${activeKeyCount}）`,
      icon: <KeyOutlined />,
      children: keysTab,
    },
  ]

  return (
    <PageContainer
      eyebrow="团队"
      title="团队管理"
      description="成员、分组与共享审批集中管理。共享按「库 × 一批人 × 一组能力」组合生效，管理员看关系不看内容。非管理员不会看到此页面入口，后端仍二次校验。"
    >
      <div className="team-layout">
        {/* 左栏：五个板块的二级导航 + 一行式状态统计 */}
        <aside className="team-side" aria-label="团队板块与概览">
          <Menu
            mode="inline"
            selectedKeys={[tab]}
            onClick={({ key }) => setTab(key)}
            items={tabItems.map(({ key, label, icon }) => ({ key, label, icon }))}
            className="team-side__menu"
          />
          <div className="team-side__stats">
            <button
              type="button"
              className="team-side__stat"
              title={`管理员 ${adminCount} 人 · 普通成员 ${memberCount} 人`}
              onClick={() => setTab('members')}
            >
              <TeamOutlined />
              <span>成员</span>
              <b>{adminCount + memberCount}</b>
            </button>
            <button
              type="button"
              className={`team-side__stat${pendingShareCount > 0 ? ' is-warning' : ''}`}
              onClick={() => setTab('shares')}
            >
              <SafetyOutlined />
              <span>待审批</span>
              <b>{pendingShareCount}</b>
            </button>
            <button
              type="button"
              className={`team-side__stat${pendingMemberCount > 0 ? ' is-warning' : ''}`}
              onClick={() => setTab('groups')}
            >
              <UsergroupAddOutlined />
              <span>待入组</span>
              <b>{pendingMemberCount}</b>
            </button>
          </div>
        </aside>

        <div className="team-main">{tabItems.find((item) => item.key === tab)?.children}</div>
      </div>

      {/* --- 分组新建 / 编辑 --- */}
      <Modal
        title={editingGroup ? `编辑分组「${editingGroup.name}」` : '新建分组'}
        open={groupModalOpen}
        onCancel={() => {
          setGroupModalOpen(false)
          setEditingGroup(null)
        }}
        onOk={() => groupForm.submit()}
        confirmLoading={submitting}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form
          form={groupForm}
          layout="vertical"
          onFinish={(values) => void handleSaveGroup(values)}
        >
          <Form.Item
            name="name"
            label="分组名"
            rules={[{ required: true, message: '请输入分组名' }, { max: 40 }]}
          >
            <Input placeholder="例如：算法组 / 论文小组" prefix={<UsergroupAddOutlined />} />
          </Form.Item>
          <Form.Item name="description" label="说明（可选）" rules={[{ max: 200 }]}>
            <Input placeholder="这个分组为什么存在、共享什么资料" />
          </Form.Item>
          {!editingGroup ? (
            <Text type="secondary">
              建组后你自动成为组内编辑者：可以拉人、审批入组申请。成员也可以自己申请加入。
            </Text>
          ) : null}
        </Form>
      </Modal>

      {/* --- 拉人入组 --- */}
      <Modal
        title={addTarget ? `邀请成员加入「${addTarget.name}」` : '邀请加入分组'}
        open={addTarget !== null}
        onCancel={() => {
          setAddTarget(null)
          setAddUserId('')
        }}
        onOk={() => void handleAddMember()}
        confirmLoading={submitting}
        okText="加入"
        cancelText="取消"
        destroyOnHidden
      >
        <Paragraph type="secondary">
          直接拉人立即生效；普通成员看不到「拉人」，只能提交申请等你审批。
        </Paragraph>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Select
            style={{ width: '100%' }}
            placeholder="选择成员"
            value={addUserId || undefined}
            onChange={setAddUserId}
            options={memberOptions.filter(
              (option) =>
                !addTarget?.members.some(
                  (member) => member.user_id === option.value && member.status === 'active',
                ),
            )}
            showSearch
            optionFilterProp="label"
            notFoundContent="没有可加入的成员"
          />
          <Select
            style={{ width: '100%' }}
            value={addRole}
            onChange={(value) => setAddRole(value as 'manager' | 'member')}
            options={[
              { value: 'member', label: '组内成员（通过分组获得共享能力）' },
              { value: 'manager', label: '组内编辑者（还能审批入组申请）' },
            ]}
          />
        </Space>
      </Modal>

      {/* --- 新建密钥 --- */}
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

      {/* --- 新增成员 --- */}
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
                { value: 'member', label: '成员（按共享获得检索与查看能力）' },
                { value: 'admin', label: '管理员（可管理成员、分组与共享审批）' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* --- 重置密码 --- */}
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
