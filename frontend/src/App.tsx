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
  QuestionCircleOutlined,
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
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'

import ErrorBoundary from './components/ErrorBoundary'
import QuickSearch from './components/QuickSearch'
import ShortcutHelp from './components/ShortcutHelp'
import { fetchMe, getCachedUser, getToken, logout, onUnauthorized } from './services/auth'
import ProviderSwitch from './components/ProviderSwitch'
import RunningTasks from './components/RunningTasks'
import { ViewStackProvider, useViewStack } from './components/ViewStack'
import { ShortcutProvider, useShortcut, useShortcuts } from './state/shortcuts'
import { useHealth } from './hooks/useHealth'
import { useIsNarrow } from './hooks/useIsNarrow'
import { NavProvider, useNav } from './state/nav'
import type { PageKey } from './state/nav'
import { TaskRunProvider, useTaskRun } from './state/taskRun'
import { APP_VERSION, BRAND_NAME, LAYOUT, buildThemeConfig } from './theme/config'
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
  key: PageKey
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
    description:
      '让 Agent 基于你的资料完成一个复杂任务。Agent 会规划任务、检索你的知识库，再分章节撰写并进行自我校验。',
  },
  {
    key: 'knowledge',
    label: '知识库',
    icon: <DatabaseOutlined />,
    title: '知识库',
    description: '上传资料构建知识库；按类别组织，按库共享给分组，任务里按范围检索。',
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
    description: '成员、分组与共享审批集中管理；共享按「库 × 一批人 × 一组能力」组合生效。',
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
                <ShortcutProvider>
                  <AppShell
                    mode={mode}
                    resolvedMode={resolvedMode}
                    setMode={setMode}
                    toggleMode={toggleMode}
                    onLogout={() => void handleLogout()}
                  />
                </ShortcutProvider>
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
  const { overlays, canGoBack, back, closeAll } = useViewStack()
  const { setHelpOpen, searchOpen, setSearchOpen, register, unregister } = useShortcuts()

  const menuTheme = resolvedMode === 'dark' ? 'dark' : 'light'
  const healthy = health?.status === 'ok'
  const healthColor = !loaded ? 'default' : healthy ? 'success' : 'error'
  const isLocalModel = Boolean(health?.llm_local)
  // 模型名只在上方选择器显示一次；状态行只说连接结论，避免重复
  const healthText = !loaded ? '检查中…' : healthy ? '已连接' : '后端未连接'
  const healthDetail = healthy
    ? `${isLocalModel ? '本地 · ' : ''}${health?.llm_model || health?.llm_label || '模型'} 已连接。${
        health?.llm_configured ? '模型服务已就绪' : '尚未配置 API Key'
      }`
    : '无法连接后端（请确认 FastAPI 已启动）'

  // 侧栏底部唯一的刷新入口：同时重拉健康状态和当前页数据，
  // 不再在顶栏和状态卡片里各放一个，避免同一个动作出现两处按钮
  const refreshAll = useCallback(() => {
    reload()
    window.dispatchEvent(new CustomEvent('app:refresh'))
  }, [reload])

  // 成员管理只对管理员开放：非管理员不显示入口（后端仍会二次校验）
  const userRole = getCachedUser()?.role
  const visiblePages = useMemo(
    () => PAGE_META.filter((item) => item.key !== 'team' || userRole === 'admin'),
    [userRole],
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

  const handleNav = useCallback(
    (key: PageKey) => {
      // 从侧栏切页时退出所有叠加视图，回到正常浏览
      closeAll()
      navigate(key)
      setDrawerOpen(false)
    },
    [closeAll, navigate],
  )

  // 统一快捷键：动作在应用壳注册，HELP 面板与按键提示共用同一份元数据
  useShortcut('help', () => setHelpOpen(true))
  useShortcut('search', () => setSearchOpen(true))
  useShortcut('toggleTheme', () => toggleMode())
  useShortcut('goBack', () => {
    // 搜索面板打开时 Esc 先关它，不误触内容区的「返回上一层」
    if (searchOpen) {
      setSearchOpen(false)
      return
    }
    if (!canGoBack) return false
    back()
  })
  // G 序列的动作 id 随可见页面动态生成，用 effect 注册而不是在循环里调 hook
  useEffect(() => {
    const ids = visiblePages.map((item) => {
      const id = `page:${item.key}`
      register(id, () => handleNav(item.key), true)
      return id
    })
    return () => ids.forEach(unregister)
  }, [visiblePages, handleNav, register, unregister])

  const nav = (
    <>
      <div className="brand">
        <div className="brand-logo">AI</div>
        <div className="brand-text">
          <div className="brand-name">{BRAND_NAME}</div>
          <div className="brand-subtitle">{APP_VERSION}</div>
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
        {/* 一条：左侧模型（点击切换）+ 右侧连接状态小点，悬停看详情 */}
        <div className="sider-system">
          {healthy ? (
            <ProviderSwitch
              activeProvider={health?.llm_provider ?? ''}
              // 任一任务在跑时禁止切换模型：避免同一次运行混用两个 Provider
              running={running || runningTasks.length > 0}
              onSwitched={reload}
            />
          ) : (
            <span className="sider-system__offline">{healthText}</span>
          )}
          <Tooltip title={healthDetail} placement="topLeft">
            <span className="sider-system__dot" aria-label={healthDetail}>
              <Badge status={healthColor} />
            </span>
          </Tooltip>
        </div>
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
          <Tooltip title="刷新（状态与当前页数据）">
            <Button
              type="text"
              size="small"
              aria-label="刷新"
              icon={<ReloadOutlined />}
              onClick={refreshAll}
            />
          </Tooltip>
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
            {/* 页面操作按钮（导入 / 导出 / 新增）统一挂在顶栏右上角；
                刷新入口在侧栏底部（退出登录左侧），此处不再重复 */}
            <div className="app-header-page-actions" data-page-actions-slot={page} />
            <Tooltip title="快捷键（? 或 F1）">
              <Button
                type="text"
                size="small"
                aria-label="快捷键帮助"
                icon={<QuestionCircleOutlined />}
                onClick={() => setHelpOpen(true)}
              />
            </Tooltip>
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
      <ShortcutHelp />
      <QuickSearch />
    </Layout>
  )
}
