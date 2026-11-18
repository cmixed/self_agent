import { LockOutlined, MailOutlined, UserOutlined } from '@ant-design/icons'
import { App, Button, Card, Form, Input, Typography } from 'antd'
import { useState } from 'react'

import {
  confirmPasswordReset,
  login,
  requestPasswordReset,
} from '../services/auth'
import { BRAND_NAME, BRAND_SUBTITLE } from '../theme/config'

interface LoginValues {
  account: string
  password: string
}

interface ResetValues {
  account: string
  code: string
  new_password: string
  confirm_password: string
}

/** 登录页：账号密码登录；忘记密码走邮箱验证码。 */
export default function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const { message } = App.useApp()
  const [mode, setMode] = useState<'login' | 'reset'>('login')
  const [submitting, setSubmitting] = useState(false)
  const [codeSent, setCodeSent] = useState(false)
  const [hint, setHint] = useState('')
  const [resetForm] = Form.useForm<ResetValues>()

  const handleLogin = async (values: LoginValues) => {
    setSubmitting(true)
    try {
      await login(values.account.trim(), values.password)
      message.success('登录成功')
      onSuccess()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSendCode = async () => {
    const account = (resetForm.getFieldValue('account') as string | undefined)?.trim()
    if (!account) {
      message.warning('请先填写用户名或邮箱')
      return
    }
    setSubmitting(true)
    try {
      const result = await requestPasswordReset(account)
      setCodeSent(true)
      setHint(result.message)
      message.success(result.message)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '发送失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleReset = async (values: ResetValues) => {
    if (values.new_password !== values.confirm_password) {
      message.warning('两次输入的新密码不一致')
      return
    }
    setSubmitting(true)
    try {
      await confirmPasswordReset(values.account.trim(), values.code.trim(), values.new_password)
      message.success('密码已重置，请用新密码登录')
      setMode('login')
      setCodeSent(false)
      setHint('')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '重置失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-shell">
      <Card className="login-card" variant="borderless">
        <div className="login-brand">
          <div className="brand-logo">AI</div>
          <div>
            <Typography.Title level={3} style={{ margin: 0 }}>
              {BRAND_NAME}
            </Typography.Title>
            <Typography.Text type="secondary">{BRAND_SUBTITLE}</Typography.Text>
          </div>
        </div>

        {mode === 'login' ? (
          <Form<LoginValues> layout="vertical" onFinish={handleLogin} requiredMark={false}>
            <Form.Item
              name="account"
              label="账号"
              rules={[{ required: true, message: '请输入用户名或邮箱' }]}
            >
              <Input
                size="large"
                prefix={<UserOutlined />}
                placeholder="用户名或邮箱"
                autoComplete="username"
              />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password
                size="large"
                prefix={<LockOutlined />}
                placeholder="密码"
                autoComplete="current-password"
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" size="large" block loading={submitting}>
              登录
            </Button>
            <div className="login-links">
              <Button type="link" size="small" onClick={() => setMode('reset')}>
                忘记密码
              </Button>
            </div>
          </Form>
        ) : (
          <Form<ResetValues>
            form={resetForm}
            layout="vertical"
            onFinish={handleReset}
            requiredMark={false}
          >
            <Form.Item
              name="account"
              label="账号"
              rules={[{ required: true, message: '请输入用户名或邮箱' }]}
            >
              <Input size="large" prefix={<UserOutlined />} placeholder="用户名或邮箱" />
            </Form.Item>
            <Form.Item label="验证码">
              <div className="login-code-row">
                <Form.Item
                  name="code"
                  noStyle
                  rules={[{ required: true, message: '请输入验证码' }]}
                >
                  <Input size="large" prefix={<MailOutlined />} placeholder="6 位验证码" />
                </Form.Item>
                <Button size="large" onClick={handleSendCode} loading={submitting}>
                  {codeSent ? '重新发送' : '发送验证码'}
                </Button>
              </div>
            </Form.Item>
            {hint ? <Typography.Text type="secondary">{hint}</Typography.Text> : null}
            <Form.Item
              name="new_password"
              label="新密码"
              rules={[
                { required: true, message: '请输入新密码' },
                { min: 8, message: '至少 8 位' },
              ]}
            >
              <Input.Password size="large" prefix={<LockOutlined />} placeholder="至少 8 位" />
            </Form.Item>
            <Form.Item
              name="confirm_password"
              label="确认新密码"
              dependencies={['new_password']}
              rules={[{ required: true, message: '请再次输入新密码' }]}
            >
              <Input.Password size="large" prefix={<LockOutlined />} placeholder="再次输入" />
            </Form.Item>
            <Button type="primary" htmlType="submit" size="large" block loading={submitting}>
              重置密码
            </Button>
            <div className="login-links">
              <Button type="link" size="small" onClick={() => setMode('login')}>
                返回登录
              </Button>
            </div>
          </Form>
        )}
      </Card>
    </div>
  )
}
