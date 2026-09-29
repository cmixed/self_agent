import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 前后端分离：开发时通过代理把 /api 转发到 FastAPI，避免跨域问题。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
