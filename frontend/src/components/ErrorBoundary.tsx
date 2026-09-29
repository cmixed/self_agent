import { Button, Result, Typography } from 'antd'
import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

const { Paragraph } = Typography

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * 渲染错误兜底：避免任一页面异常导致整页白屏（答辩保险）。
 * 只影响前端渲染，不改变任何接口行为。
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 仅输出到控制台，便于排查；不向后端上报
    console.error('[ui] 页面渲染异常', error, info.componentStack)
  }

  private handleReload = () => {
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) {
      return this.props.children
    }
    return (
      <Result
        status="error"
        title="页面渲染出错"
        subTitle="可以重试；若持续出现请查看浏览器控制台，后端服务不受影响。"
        extra={[
          <Button type="primary" key="retry" onClick={this.handleReload}>
            重试
          </Button>,
          <Button key="reload" onClick={() => window.location.reload()}>
            刷新页面
          </Button>,
        ]}
      >
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {error.message}
        </Paragraph>
      </Result>
    )
  }
}
