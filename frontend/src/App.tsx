import {
  ApiOutlined,
  CloudServerOutlined,
  BulbOutlined,
  DatabaseOutlined,
  HistoryOutlined,
  MenuFoldOutlined,
  MenuOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  ReloadOutlined,
  RocketOutlined,
  SettingOutlined,
  SunOutlined,
  TagsOutlined,
  TeamOutlined,
  LogoutOutlined,
} from '@ant-design/icons'
import {
  App as AntApp,
  Avatar,
  Badge,
  Button,
  ConfigProvider,
  Drawer,
  Layout,
  Menu,
  Spin,
  Tooltip,
} from 'antd'
import type { MenuProps } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import type { ReactNode } from 'react'
import { lazy, Suspense, useEffect, useState } from 'react'

import ErrorBoundary from './components/ErrorBoundary'
import { fetchMe, getCachedUser, getToken, logout, onUnauthorized } from './services/auth'
import ProviderSwitch, { providerLabelOf } from './components/ProviderSwitch'
import RunningTasks from './components/RunningTasks'
import { ViewStackProvider, useViewStack } from './components/ViewStack'
import { useHealth } from './hooks/useHealth'
import { useIsNarrow } from './hooks/useIsNarrow'
import { NavProvider, useNav } from './state/nav'
import type { PageKey } from './state/nav'
import { TaskRunProvider, useTaskRun } from './state/taskRun'
import { APP_VERSION, BRAND_NAME, BRAND_SUBTITLE, LAYOUT, buildThemeConfig } from './theme/config'
import type { ResolvedTheme, ThemeMode } from './theme/config'
import { useUiPreferences } from './theme/useUiPreferences'

// 页面与叠加视图按需加载：首屏只解析应用壳，页面重依赖（Markdown / 表格等）随路由拆包。
const TaskPage = lazy(() => import('./pages/Task'))
const KnowledgeBasePage = lazy(() => import('./pages/KnowledgeBase'))
const SkillsPage = lazy(() => import('./pages/Skills'))
const PresetsPage = lazy(() => import('./pages/Presets'))
const ProvidersPage = lazy(() => import('./pages/Providers'))
const HistoryPage = lazy(() => import('./pages/History'))
const MemoryPage = lazy(() => import('./pages/Memory'))
const TeamPage = lazy(() => import('./pages/Members'))
const SettingsPage = lazy(() => import('./pages/Settings'))
const LoginPage = lazy(() => import('./pages/Login'))

const DocumentView = lazy(() => import('./components/DocumentView'))
const SkillView = lazy(() => import('./components/SkillView'))
const TaskDetailView = lazy(() => import('./components/TaskDetailView'))

/** 懒加载占位：与应用壳同色，避免切页时闪白。 */
function PageFallback() {
  return (
    <div className="app-loading">
      <Spin />
    </div>
  )
}

const { Content, Sider } = Layout

interface PageMeta {
  key: string
  label: string
  icon: ReactNode
  /** 顶栏主标题：加粗提亮 */
  title: string
  /** 顶栏副标题：一句话说明该板块 */
  description: string
}

const PAGE_META: PageMeta[] = [
  {
    key: 'workspace',
    label: '工作台',
    icon: <RocketOutlined />,
    title: '工作台',
    description: '让 Agent 基于你的资料完成一个复杂任务。Agent 会规划任务、检索你的知识库，再分章节撰写并进行自我校验。',
  },
  {
    key: 'knowledge',
    label: '知识库',
    icon: <DatabaseOutlined />,
    title: '知识库',
    description: '上传资料，构建你的知识库；按类别组织，任务里按范围检索。',
  },
  {
    key: 'presets',
    label: '预设任务',
    icon: <TagsOutlined />,
    title: '预设任务',
    description: '管理工作台的快捷任务；点击卡片填入输入框，「直接运行」立即执行。',
  },
  {
    key: 'history',
    label: '任务历史',
    icon: <HistoryOutlined />,
    title: '任务历史',
    description: '查看过去任务的执行状态与结果；点击任务可查看正文、来源与校验结论。',
  },
  {
    key: 'skills',
    label: '技能',
    icon: <ApiOutlined />,
    title: '技能',
    description: '让 Agent 在任务中调用你的技能；技能以标准 SKILL.md 目录保存。',
  },
  {
    key: 'memory',
    label: '长期记忆',
    icon: <BulbOutlined />,
    title: '长期记忆',
    description: '管理跨任务保留的偏好与信息；偏好会在后续任务中按模式生效。',
  },
  {
    key: 'team',
    label: '团队管理',
    icon: <TeamOutlined />,
    title: '团队管理',
    description: '同一团队共享知识库；成员、权限与对外接口集中管理。',
  },
  {
    key: 'providers',
    label: '模型服务',
    icon: <CloudServerOutlined />,
    title: '模型服务',
    description: '接入你自己的模型接口；支持 OpenAI 兼容端点与本地 Ollama。',
  },
  {
    key: 'settings',
    label: '设置',
    icon: <SettingOutlined />,
    title: '设置',
    description: '管理长期偏好与提醒；偏好只保存在当前浏览器。',
  },
]

export default function App() {
  const { mode, resolvedMode, setMode, toggleMode } = useUiPreferences()
  // null = 正在校验登录态；false = 未登录（显示登录页）
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    let alive = true
    onUnauthorized(() => {
      if (alive) setAuthed(false)
    })
    const bootstrap = async () => {
      if (!getToken()) {
        if (alive) setAuthed(false)
        return
      }
      try {
        await fetchMe()
        if (alive) setAuthed(true)
      } catch {
        if (alive) setAuthed(false)
      }
    }
    void bootstrap()
    return () => {
      alive = false
      onUnauthorized(null)
    }
  }, [])

  const handleLogout = async () => {
    await logout()
    setAuthed(false)
  }

  return (
    <ConfigProvider locale={zhCN} theme={buildThemeConfig(resolvedMode)}>
      <AntApp>
        {authed === null ? (
          <div className="app-loading">
            <Spin />
          </div>
        ) : authed === false ? (
          <Suspense fallback={<PageFallback />}>
            <LoginPage onSuccess={() => setAuthed(true)} />
          </Suspense>
        ) : (
          /* 任务运行状态提升到 App 层：切换页面不丢进度，任务继续在后台执行 */
          <NavProvider>
            <TaskRunProvider>
              <ViewStackProvider>
                <AppShell
                  mode={mode}
                  resolvedMode={resolvedMode}
                  setMode={setMode}
                  toggleMode={toggleMode}
                  onLogout={() => void handleLogout()}
                />
              </ViewStackProvider>
            </TaskRunProvider>
          </NavProvider>
        )}
      </AntApp>
    </ConfigProvider>
  )
}

function AppShell({
  mode,
  resolvedMode,
  setMode,
  toggleMode,
  onLogout,
}: {
  mode: ThemeMode
  resolvedMode: ResolvedTheme
  setMode: (mode: ThemeMode) => void
  toggleMode: () => void
  onLogout: () => void
}) {
  const { page, navigate } = useNav()
  const [collapsed, setCollapsed] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const narrow = useIsNarrow()

  const { health, loaded, reload } = useHealth()
  const { running, runningTasks } = useTaskRun()
  const { overlays, closeAll } = useViewStack()

  const menuTheme = resolvedMode === 'dark' ? 'dark' : 'light'
  const healthy = health?.status === 'ok'
  const healthColor = !loaded ? 'default' : healthy ? 'success' : 'error'
  // 展示「模型名」而不是内部 provider id（如 custom-ba45f8fa）
  const displayName =
    health?.llm_model || health?.llm_label || providerLabelOf(health?.llm_provider ?? '')
  const isLocalModel = Boolean(health?.llm_local)
  const healthText = !loaded
    ? '检查中…'
    : healthy
      ? `${isLocalModel ? '本地 · ' : ''}${displayName} 已连接`
      : '后端未连接'
  const healthDetail = healthy
    ? health?.llm_configured
      ? isLocalModel
        ? '本地模型服务已就绪（无需 API Key）'
        : '后端与模型配置正常'
      : isLocalModel
        ? '本地模型服务尚未选择模型，请到「模型服务」页设置'
        : '后端正常，但尚未配置模型 API Key'
    : '无法连接后端（请确认 FastAPI 已启动）'

  // 成员管理只对管理员开放：非管理员不显示入口（后端仍会二次校验）
  const visiblePages = PAGE_META.filter(
    (item) => item.key !== 'team' || getCachedUser()?.role === 'admin',
  )
  // 「团队管理 / 模型服务 / 设置」属于配置类页面，整组放在分隔线下方；
  // 非管理员看不到团队管理时，线自动上移到「模型服务」之前。
  const configGroupStart = visiblePages.findIndex(
    (item) => item.key === 'team' || item.key === 'providers' || item.key === 'settings',
  )
  const menuItems: MenuProps['items'] = visiblePages.flatMap((item, index) => {
    const entry: NonNullable<MenuProps['items']>[number] = {
      key: item.key,
      label: item.label,
      // 有任务在跑时在图标上显示小圆点（折叠状态下也可见）
      icon:
        item.key === 'workspace' && (running || runningTasks.length > 0) ? (
          <Badge dot offset={[2, -2]}>
            {item.icon}
          </Badge>
        ) : (
          item.icon
        ),
    }
    // 配置类页面整组之前加一条分隔线
    return index === configGroupStart ? [{ type: 'divider' as const }, entry] : [entry]
  })

  const handleNav = (key: PageKey) => {
    // 从侧栏切页时退出所有叠加视图，回到正常浏览
    closeAll()
    navigate(key)
    setDrawerOpen(false)
  }

  const nav = (
    <>
      <div className="brand">
        <div className="brand-logo">AI</div>
        <div className="brand-text">
          <div className="brand-name">{BRAND_NAME}</div>
          <div className="brand-subtitle">{BRAND_SUBTITLE}</div>
        </div>
      </div>
      <Menu
        className="app-menu"
        theme={menuTheme}
        mode="inline"
        selectedKeys={[page]}
        items={menuItems}
        onClick={(event) => handleNav(event.key as PageKey)}
      />
      <div className="sider-footer">
        {healthy ? (
          <div className="sider-provider">
            <ProviderSwitch
              activeProvider={health?.llm_provider ?? ''}
              // 任一任务在跑时禁止切换模型：避免同一次运行混用两个 Provider
              running={running || runningTasks.length > 0}
              onSwitched={reload}
            />
          </div>
        ) : null}
        <Tooltip title={healthDetail} placement="right">
          <div className="health-row">
            <Badge status={healthColor} />
            <span className="health-text">{healthText}</span>
            <Button
              type="text"
              size="small"
              aria-label="重新检查后端状态"
              icon={<ReloadOutlined />}
              onClick={reload}
            />
          </div>
        </Tooltip>
        <div className="sider-account">
          <Avatar size={28} className="sider-account-avatar">
            {(getCachedUser()?.display_name || '?').slice(0, 1).toUpperCase()}
          </Avatar>
          <div className="sider-account-meta">
            <span className="sider-account-name">{getCachedUser()?.display_name || '成员'}</span>
            <span className="sider-account-role">
              {getCachedUser()?.role === 'admin' ? '管理员' : '成员'}
            </span>
          </div>
          <Tooltip title="退出登录">
            <Button
              type="text"
              size="small"
              aria-label="退出登录"
              icon={<LogoutOutlined />}
              onClick={onLogout}
            />
          </Tooltip>
        </div>
        <div className="sider-version">{APP_VERSION}</div>
      </div>
    </>
  )

  return (
    <Layout className="app-shell">
      {narrow ? (
        <Drawer
          placement="left"
          width={LAYOUT.drawerWidth}
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          closable={false}
          styles={{ body: { padding: 0 } }}
        >
          <div className="app-sider app-sider--drawer">{nav}</div>
        </Drawer>
      ) : (
        <Sider
          className="app-sider"
          theme={menuTheme}
          width={LAYOUT.sidebarWidth}
          collapsedWidth={LAYOUT.sidebarCollapsedWidth}
          collapsed={collapsed}
          trigger={null}
        >
          {nav}
        </Sider>
      )}

      <Layout>
        <div className="app-header">
          {narrow ? (
            <Button
              type="text"
              aria-label="打开导航"
              icon={<MenuOutlined />}
              onClick={() => setDrawerOpen(true)}
            />
          ) : (
            <Button
              type="text"
              aria-label={collapsed ? '展开侧边栏' : '折叠侧边栏'}
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((prev) => !prev)}
            />
          )}
          <div className="app-header-title">
            <span className="app-header-title__name">
              {PAGE_META.find((item) => item.key === page)?.title}
            </span>
            <span className="app-header-title__desc">
              {PAGE_META.find((item) => item.key === page)?.description}
            </span>
          </div>
          <div className="app-header-actions">
            <RunningTasks />
            <Tooltip
              title={
                mode === 'system'
                  ? `跟随系统（当前${resolvedMode === 'dark' ? '深色' : '浅色'}），点击切换为固定主题`
                  : resolvedMode === 'dark'
                    ? '切换到浅色'
                    : '切换到深色'
              }
            >
              <Button
                type="text"
                size="small"
                aria-label="切换主题"
                icon={resolvedMode === 'dark' ? <SunOutlined /> : <MoonOutlined />}
                onClick={toggleMode}
              />
            </Tooltip>
          </div>
        </div>

        <Content className="app-content">
          <ErrorBoundary>
            {/* 页面常驻挂载；叠加视图隐藏它，返回时列表与状态不丢 */}
            <div className={overlays.length === 0 ? 'app-layer' : 'app-layer is-hidden'}>
              <Suspense fallback={<PageFallback />}>
                {page === 'workspace' && <TaskPage />}
                {page === 'knowledge' && <KnowledgeBasePage />}
                {page === 'skills' && <SkillsPage />}
                {page === 'presets' && <PresetsPage />}
                {page === 'providers' && <ProvidersPage />}
                {page === 'history' && <HistoryPage />}
                {page === 'memory' && <MemoryPage />}
                {page === 'team' && <TeamPage />}
                {page === 'settings' && <SettingsPage mode={mode} setMode={setMode} />}
              </Suspense>
            </div>
            {/* 叠加视图（任务详情 / 文档阅读），可嵌套返回 */}
            {overlays.map((entry, index) => (
              <div
                key={entry.id}
                className={index === overlays.length - 1 ? 'app-layer' : 'app-layer is-hidden'}
              >
                <Suspense fallback={<PageFallback />}>
                  {entry.view.kind === 'document' ? (
                    <DocumentView
                      documentId={entry.view.documentId}
                      filename={entry.view.filename}
                    />
                  ) : entry.view.kind === 'skill' ? (
                    <SkillView skill={entry.view.skill} />
                  ) : (
                    <TaskDetailView taskId={entry.view.taskId} />
                  )}
                </Suspense>
              </div>
            ))}
          </ErrorBoundary>
        </Content>
      </Layout>
    </Layout>
  )
}
