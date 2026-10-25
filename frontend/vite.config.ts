import react from '@vitejs/plugin-react'
import { defineConfig, lazyPlugins } from 'vite-plus'

// 前后端分离：开发时通过代理把 /api 转发到 FastAPI，避免跨域问题。
export default defineConfig({
  fmt: {
    // 与项目既有风格保持一致，避免迁移时产生无意义的全量重排
    singleQuote: true,
    semi: false,
    printWidth: 100,
  },
  lint: {
    jsPlugins: [{ name: 'vite-plus', specifier: 'vite-plus/oxlint-plugin' }],
    rules: { 'vite-plus/prefer-vite-plus-imports': 'error' },
    options: { typeAware: true, typeCheck: true },
  },
  test: {
    // 纯逻辑测试用 node；需要 DOM 的文件在文件头用 @vitest-environment 覆盖
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
  plugins: lazyPlugins(() => [react()]),
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
