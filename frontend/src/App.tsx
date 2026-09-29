import { Layout, Typography } from 'antd'

import ChatPage from './pages/Chat'

const { Header, Content } = Layout
const { Title } = Typography

export default function App() {
  return (
    <Layout style={{ minHeight: '100%' }}>
      <Header style={{ display: 'flex', alignItems: 'center' }}>
        <Title level={4} style={{ color: '#fff', margin: 0 }}>
          基于 RAG 的个人任务型智能体
        </Title>
      </Header>
      <Content style={{ padding: 24 }}>
        <ChatPage />
      </Content>
    </Layout>
  )
}
