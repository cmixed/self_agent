import { Alert, Button, Card, Input, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { ApiError, getHealth, sendChat } from '../services/api'
import type { ChatMessage, HealthResponse } from '../types/api'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const ROLE_LABEL: Record<ChatMessage['role'], string> = {
  system: '系统',
  user: '我',
  assistant: 'Agent',
}

export default function ChatPage() {
  const [history, setHistory] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  const canSend = input.trim().length > 0 && !loading

  const handleSend = async () => {
    const content = input.trim()
    if (!content || loading) return

    const nextHistory: ChatMessage[] = [...history, { role: 'user', content }]
    setHistory(nextHistory)
    setInput('')
    setLoading(true)
    setError(null)

    try {
      const response = await sendChat(nextHistory)
      setHistory([...nextHistory, { role: 'assistant', content: response.answer }])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '请求失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%', maxWidth: 900, margin: '0 auto' }}>
      <Space>
        <Text type="secondary">后端状态：</Text>
        {health ? (
          <Tag color={health.status === 'ok' ? 'green' : 'red'}>
            {health.status} · {health.llm_provider}
            {health.llm_configured ? '' : '（未配置 API Key）'}
          </Tag>
        ) : (
          <Tag color="default">无法连接后端</Tag>
        )}
      </Space>

      <Card title="对话" styles={{ body: { minHeight: 320 } }}>
        {history.length === 0 ? (
          <Text type="secondary">输入一个问题开始对话（Phase 1 直连 DeepSeek，暂未接入知识库）。</Text>
        ) : (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {history.map((message, index) => (
              <div key={index}>
                <Text strong>{ROLE_LABEL[message.role]}：</Text>
                <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                  {message.content}
                </Paragraph>
              </div>
            ))}
          </Space>
        )}
      </Card>

      {error && <Alert type="error" showIcon message={error} />}

      <TextArea
        rows={3}
        value={input}
        placeholder="例如：用一句话解释什么是 RAG"
        onChange={(event) => setInput(event.target.value)}
        onPressEnter={(event) => {
          if (!event.shiftKey) {
            event.preventDefault()
            void handleSend()
          }
        }}
      />

      <Space>
        <Button type="primary" loading={loading} disabled={!canSend} onClick={() => void handleSend()}>
          发送
        </Button>
        <Button
          disabled={loading || history.length === 0}
          onClick={() => {
            setHistory([])
            setError(null)
          }}
        >
          清空
        </Button>
      </Space>
    </Space>
  )
}
