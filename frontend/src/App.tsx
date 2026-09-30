import {
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
} from '@ant-design/icons'
import {
  App as AntApp,
  Badge,
  Button,
  ConfigProvider,
  Drawer,
  Layout,
  Menu,
  Tooltip,
} from 'antd'
import zhCN from 'antd/locale/zh_CN'
import type { ReactNode } from 'react'
import { useState } from 'react'

import ErrorBoundary from './components/ErrorBoundary'
import { useHealth } from './hooks/useHealth'
import { useIsNarrow } from './hooks/useIsNarrow'
import HistoryPage from './pages/History'
import KnowledgeBasePage from './pages/KnowledgeBase'
import MemoryPage from './pages/Memory'
import TaskPage from './pages/Task'
import { NavProvider, useNav } from './state/nav'
import type { PageKey } from './state/nav'
import { TaskRunProvider, useTaskRun } from './state/taskRun'
import { APP_VERSION, BRAND_NAME, BRAND_SUBTITLE, LAYOUT, buildThemeConfig } from './theme/config'
import { useUiPreferences } from './theme/useUiPreferences'

const { Content, Sider } = Layout

const PAGE_META: Array<{ key: string; label: string; icon: ReactNode }> = [
  { key: 'workspace', label: '工作台', icon: <RocketOutlined /> },
  { key: 'knowledge', label: '知识库', icon: <DatabaseOutlined /> },
  { key: 'history', label: '任务历史', icon: <HistoryOutlined /> },
  { key: 'memory', label: '长期记忆', icon: <BulbOutlined /> },
]

export default function App() {
  const { mode, toggleMode } = useUiPreferences()

  return (
    <ConfigProvider locale={zhCN} theme={buildThemeConfig(mode)}>
      <AntApp>
        {/* 任务运行状态提升到 App 层：切换页面不丢进度，任务继续在后台执行 */}
        <TaskRunProvider>
          <NavProvider>
            <AppShell mode={mode} toggleMode={toggleMode} />
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

  const menuTheme = mode === 'dark' ? 'dark' : 'light'
  const healthy = health?.status === 'ok'
  const healthColor = !loaded ? 'default' : healthy ? 'success' : 'error'
  const providerKey = (health?.llm_provider ?? '').toLowerCase()
  const providerLabel =
    { deepseek: 'DeepSeek', ollama: 'Ollama' }[providerKey] ??
    (providerKey ? providerKey.charAt(0).toUpperCase() + providerKey.slice(1) : '')
  const healthText = !loaded ? '检查中…' : healthy ? `${providerLabel} 已连接` : '后端未连接'
  const healthDetail = healthy
    ? health?.llm_configured
      ? '后端与模型配置正常'
      : '后端正常，但尚未配置 DEEPSEEK_API_KEY'
    : '无法连接后端（请确认 FastAPI 已启动）'

  const currentLabel = PAGE_META.find((item) => item.key === page)?.label ?? ''

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
          <span className="app-header-title">{currentLabel}</span>

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
            {page === 'workspace' && <TaskPage />}
            {page === 'knowledge' && <KnowledgeBasePage />}
            {page === 'history' && <HistoryPage />}
            {page === 'memory' && <MemoryPage />}
          </ErrorBoundary>
        </Content>
      </Layout>
    </Layout>
  )
}
