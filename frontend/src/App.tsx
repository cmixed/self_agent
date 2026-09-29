import {
  BulbOutlined,
  DatabaseOutlined,
  HistoryOutlined,
  MenuFoldOutlined,
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
  Layout,
  Menu,
  Space,
  Switch,
  Tooltip,
} from 'antd'
import zhCN from 'antd/locale/zh_CN'
import type { ReactNode } from 'react'
import { useState } from 'react'

import ErrorBoundary from './components/ErrorBoundary'
import { useHealth } from './hooks/useHealth'
import HistoryPage from './pages/History'
import KnowledgeBasePage from './pages/KnowledgeBase'
import MemoryPage from './pages/Memory'
import TaskPage from './pages/Task'
import { TaskRunProvider, useTaskRun } from './state/taskRun'
import { APP_VERSION, BRAND_NAME, BRAND_SUBTITLE, buildThemeConfig } from './theme/config'
import { useUiPreferences } from './theme/useUiPreferences'

const { Content, Sider } = Layout

const PAGE_META: Array<{ key: string; label: string; icon: ReactNode }> = [
  { key: 'task', label: '任务', icon: <RocketOutlined /> },
  { key: 'knowledge', label: '知识库', icon: <DatabaseOutlined /> },
  { key: 'history', label: '任务历史', icon: <HistoryOutlined /> },
  { key: 'memory', label: '长期记忆', icon: <BulbOutlined /> },
]

export default function App() {
  const { mode, toggleMode, mica, toggleMica } = useUiPreferences()

  return (
    <ConfigProvider locale={zhCN} theme={buildThemeConfig(mode)}>
      <AntApp>
        {/* 任务运行状态提升到 App 层：切换页面不丢进度，任务继续在后台执行 */}
        <TaskRunProvider>
          <AppShell
            mode={mode}
            toggleMode={toggleMode}
            mica={mica}
            toggleMica={toggleMica}
          />
        </TaskRunProvider>
      </AntApp>
    </ConfigProvider>
  )
}

function AppShell({
  mode,
  toggleMode,
  mica,
  toggleMica,
}: {
  mode: 'dark' | 'light'
  toggleMode: () => void
  mica: boolean
  toggleMica: () => void
}) {
  const [page, setPage] = useState('task')
  const [collapsed, setCollapsed] = useState(false)
  const { health, loaded, reload } = useHealth()
  const { running } = useTaskRun()

  const menuTheme = mode === 'dark' ? 'dark' : 'light'
  const healthy = health?.status === 'ok'
  const healthColor = !loaded ? 'default' : healthy ? 'success' : 'error'
  const healthText = !loaded ? '检查中…' : healthy ? `${health?.llm_provider} 就绪` : '后端未连接'
  const healthDetail = healthy
    ? health?.llm_configured
      ? '后端与模型配置正常'
      : '后端正常，但尚未配置 DEEPSEEK_API_KEY'
    : '无法连接后端（请确认 FastAPI 已启动）'

  const menuItems = PAGE_META.map((item) => ({
    key: item.key,
    label: item.label,
    // 任务运行中时在图标上显示小圆点（折叠状态下也可见）
    icon:
      item.key === 'task' && running ? (
        <Badge dot offset={[2, -2]}>
          {item.icon}
        </Badge>
      ) : (
        item.icon
      ),
  }))

  return (
    <>
      {/* 静态柔和底衬：为 Mica 面板提供可模糊的内容（无动画） */}
      <div className="app-backdrop" aria-hidden="true" />

      <Layout className="app-shell">
        <Sider
          className="app-sider surface-mica"
          theme={menuTheme}
          width={232}
          collapsedWidth={72}
          collapsed={collapsed}
          trigger={null}
          breakpoint="lg"
          onBreakpoint={(broken) => setCollapsed(broken)}
        >
          <div className="brand">
            <div className="brand-logo">AI</div>
            {!collapsed && (
              <div className="brand-text">
                <div className="brand-name">{BRAND_NAME}</div>
                <div className="brand-subtitle">{BRAND_SUBTITLE}</div>
              </div>
            )}
          </div>

          <Menu
            className="app-menu"
            theme={menuTheme}
            mode="inline"
            selectedKeys={[page]}
            items={menuItems}
            onClick={(event) => setPage(event.key)}
          />

          <div className="sider-footer">
            <Tooltip title={healthDetail} placement="right">
              <div className="health-row">
                <Badge status={healthColor} />
                {!collapsed && <span className="health-text">{healthText}</span>}
              </div>
            </Tooltip>

            <Space size={4} className="sider-actions">
              <Tooltip title={mode === 'dark' ? '切换到浅色' : '切换到深色'} placement="top">
                <Button
                  type="text"
                  size="small"
                  aria-label="切换主题"
                  icon={mode === 'dark' ? <SunOutlined /> : <MoonOutlined />}
                  onClick={toggleMode}
                />
              </Tooltip>
              {!collapsed && (
                <Tooltip title="毛玻璃（Mica）效果" placement="top">
                  <span className="mica-switch">
                    <Switch size="small" checked={mica} onChange={toggleMica} />
                    <span className="mica-label">毛玻璃</span>
                  </span>
                </Tooltip>
              )}
              <Tooltip title="重新检查后端状态" placement="top">
                <Button
                  type="text"
                  size="small"
                  aria-label="刷新后端状态"
                  icon={<ReloadOutlined />}
                  onClick={reload}
                />
              </Tooltip>
            </Space>

            {!collapsed && <div className="sider-version">{APP_VERSION}</div>}
          </div>
        </Sider>

        <Layout>
          <div className="app-header surface-mica">
            <Button
              type="text"
              aria-label={collapsed ? '展开侧边栏' : '折叠侧边栏'}
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((prev) => !prev)}
            />
            <span className="app-header-title">
              {PAGE_META.find((item) => item.key === page)?.label ?? ''}
            </span>
            {running && (
              <span className="app-header-running">
                <Badge status="processing" /> 任务运行中
              </span>
            )}
          </div>

          <Content className="app-content">
            <ErrorBoundary>
              {page === 'task' && <TaskPage />}
              {page === 'knowledge' && <KnowledgeBasePage />}
              {page === 'history' && <HistoryPage />}
              {page === 'memory' && <MemoryPage />}
            </ErrorBoundary>
          </Content>
        </Layout>
      </Layout>
    </>
  )
}
