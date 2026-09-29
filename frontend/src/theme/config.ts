import { theme } from 'antd'
import type { ThemeConfig } from 'antd'

export type ThemeMode = 'dark' | 'light'

export const THEME_STORAGE_KEY = 'self-agent.theme'
export const MICA_STORAGE_KEY = 'self-agent.mica'

export const BRAND_NAME = '个人知识库任务型智能体'
export const BRAND_SUBTITLE = '基于 RAG 的任务型 Agent'
export const APP_VERSION = 'v0.1.0'

/** 单一 token 源：颜色随 algorithm 派生，我们自己只定义品牌与尺度。 */
export function buildThemeConfig(mode: ThemeMode): ThemeConfig {
  return {
    algorithm: mode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
    // 开启 CSS 变量模式：自定义 CSS 可直接引用 --ant-* 变量并自动跟随主题
    cssVar: { key: 'sa' },
    token: {
      colorPrimary: '#2563eb',
      borderRadius: 10,
      controlHeight: 36,
      fontSize: 14,
      fontFamily:
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    },
    components: {
      Layout: {
        // 侧栏/页头背景交给 Mica 面板，Layout 本身透明
        siderBg: 'transparent',
        lightSiderBg: 'transparent',
        headerBg: 'transparent',
        bodyBg: 'transparent',
      },
      Menu: {
        itemHeight: 40,
        itemMarginInline: 8,
        itemBorderRadius: 8,
      },
      Card: {
        headerFontSize: 15,
      },
    },
  }
}
