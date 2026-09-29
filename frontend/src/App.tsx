import { Layout, Menu, Typography } from 'antd'
import { useState } from 'react'

import HistoryPage from './pages/History'
import KnowledgeBasePage from './pages/KnowledgeBase'
import MemoryPage from './pages/Memory'
import TaskPage from './pages/Task'

const { Header, Content } = Layout
const { Title } = Typography

const PAGES = [
  { key: 'task', label: '任务' },
  { key: 'knowledge', label: '知识库' },
  { key: 'history', label: '任务历史' },
  { key: 'memory', label: '长期记忆' },
]

export default function App() {
  const [page, setPage] = useState('task')

  return (
    <Layout style={{ minHeight: '100%' }}>
      <Header style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <Title level={4} style={{ color: '#fff', margin: 0, whiteSpace: 'nowrap' }}>
          个人知识库任务型智能体
        </Title>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[page]}
          items={PAGES}
          onClick={(event) => setPage(event.key)}
          style={{ flex: 1, minWidth: 0 }}
        />
      </Header>
      <Content style={{ padding: 24 }}>
        {page === 'task' && <TaskPage />}
        {page === 'knowledge' && <KnowledgeBasePage />}
        {page === 'history' && <HistoryPage />}
        {page === 'memory' && <MemoryPage />}
      </Content>
    </Layout>
  )
}
