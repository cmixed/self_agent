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
  SunOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import {
  App as AntApp,
  Badge,
  Button,
  ConfigProvider,
  Drawer,
  Layout,
  Menu,
  Spin,
  Tooltip,
} from 'antd'
import zhCN from 'antd/locale/zh_CN'
import type { ReactNode } from 'react'
import { lazy, Suspense, useState } from 'react'

import ErrorBoundary from './components/ErrorBoundary'
import ProviderSwitch, { providerLabelOf } from './components/ProviderSwitch'
import { ViewStackProvider, useViewStack } from './components/ViewStack'
import { useHealth } from './hooks/useHealth'
import { useIsNarrow } from './hooks/useIsNarrow'
import { NavProvider, useNav } from './state/nav'
import type { PageKey } from './state/nav'
import { TaskRunProvider, useTaskRun } from './state/taskRun'
import { APP_VERSION, BRAND_NAME, BRAND_SUBTITLE, LAYOUT, buildThemeConfig } from './theme/config'
import { useUiPreferences } from './theme/useUiPreferences'

// 页面与叠加视图按需加载：首屏只解析应用壳，页面重依赖（Markdown / 表格等）随路由拆包。
const TaskPage = lazy(() => import('./pages/Task'))
const KnowledgeBasePage = lazy(() => import('./pages/KnowledgeBase'))
const SkillsPage = lazy(() => import('./pages/Skills'))
const PresetsPage = lazy(() => import('./pages/Presets'))
const ProvidersPage = lazy(() => import('./pages/Providers'))
const HistoryPage = lazy(() => import('./pages/History'))
const MemoryPage = lazy(() => import('./pages/Memory'))

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

const PAGE_META: Array<{ key: string; label: string; icon: ReactNode }> = [
  { key: 'workspace', label: '工作台', icon: <RocketOutlined /> },
  { key: 'knowledge', label: '知识库', icon: <DatabaseOutlined /> },
  { key: 'skills', label: '技能', icon: <ApiOutlined /> },
  { key: 'presets', label: '预设任务', icon: <TagsOutlined /> },
  { key: 'history', label: '任务历史', icon: <HistoryOutlined /> },
  { key: 'memory', label: '长期记忆', icon: <BulbOutlined /> },
  { key: 'providers', label: '模型服务', icon: <CloudServerOutlined /> },
]

export default function App() {
  const { mode, toggleMode } = useUiPreferences()

  return (
    <ConfigProvider locale={zhCN} theme={buildThemeConfig(mode)}>
      <AntApp>
        {/* 任务运行状态提升到 App 层：切换页面不丢进度，任务继续在后台执行 */}
        <TaskRunProvider>
          <NavProvider>
            <ViewStackProvider>
              <AppShell mode={mode} toggleMode={toggleMode} />
            </ViewStackProvider>
          </NavProvider>
        </TaskRunProvider>
      </AntApp>
    </ConfigProvider>
  )
}

function AppShell({ mode, toggleMode }: { mode: 'dark' | 'light'; toggleMode: () => void }) {
  const { page, navigate } = useNav()
  const [collapsed, setCollapsed] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const narrow = useIsNarrow()

  const { health, loaded, reload } = useHealth()
  const { running } = useTaskRun()
  const { overlays, closeAll } = useViewStack()

  const menuTheme = mode === 'dark' ? 'dark' : 'light'
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

  const menuItems = PAGE_META.map((item) => ({
    key: item.key,
    label: item.label,
    // 任务运行中时在图标上显示小圆点（折叠状态下也可见）
    icon:
      item.key === 'workspace' && running ? (
        <Badge dot offset={[2, -2]}>
          {item.icon}
        </Badge>
      ) : (
        item.icon
      ),
  }))

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
          <div className="app-header-actions">
            {running ? (
              <Tooltip title="任务正在后台执行，点击返回工作台">
                <Button
                  type="text"
                  size="small"
                  className="app-header-run"
                  aria-label="任务执行中，返回工作台"
                  onClick={() => handleNav('workspace')}
                >
                  <Badge status="processing" />
                  <span className="app-header-run__text">执行中</span>
                </Button>
              </Tooltip>
            ) : null}
            {healthy ? (
              <ProviderSwitch
                activeProvider={health?.llm_provider ?? ''}
                running={running}
                onSwitched={reload}
              />
            ) : null}
            <Tooltip title={mode === 'dark' ? '切换到浅色' : '切换到深色'}>
              <Button
                type="text"
                size="small"
                aria-label="切换主题"
                icon={mode === 'dark' ? <SunOutlined /> : <MoonOutlined />}
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
