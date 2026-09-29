import React from 'react'
import ReactDOM from 'react-dom/client'

import App from './App'
import './index.css'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('未找到 #root 挂载点')
}

// 主题与 locale 配置在 App 内（ConfigProvider），此处只负责挂载
ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
