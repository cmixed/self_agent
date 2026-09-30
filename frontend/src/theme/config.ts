import { theme } from 'antd'
import type { ThemeConfig } from 'antd'

export type ThemeMode = 'dark' | 'light'

export const THEME_STORAGE_KEY = 'self-agent.theme'

export const BRAND_NAME = '个人知识库任务型智能体'
export const BRAND_SUBTITLE = 'RAG Agent Workspace'
export const APP_VERSION = 'v0.1.0'

/** 品牌主色：仙茶绿。 */
export const BRAND_PRIMARY = '#525e54'

/**
 * 仙茶绿色阶（低饱和）。
 * 主色 #525e54 作为按钮底/描边够用（白字对比 ≈ 6.7:1），
 * 但在深色底上作文字/图标对比不足，因此文字态使用更亮的 200/300。
 */
export const SAGE = {
  200: '#a7b3a7',
  300: '#8d9c8d',
  400: '#6b7a6b',
  500: '#525e54',
  600: '#475349',
  700: '#3c473e',
} as const

/** 实色分层：深色为带一丝绿的冷灰，浅色为中性白。 */
const SURFACE = {
  dark: {
    layout: '#0b0d0c',
    container: '#121514',
    elevated: '#171b19',
    border: '#262c29',
    borderSecondary: '#1d2220',
    fill: '#1a1f1d',
    tableHeader: '#161a18',
  },
  light: {
    layout: '#f5f6f5',
    container: '#ffffff',
    elevated: '#ffffff',
    border: '#e3e6e4',
    borderSecondary: '#eceeec',
    fill: '#f2f4f3',
    tableHeader: '#f5f6f5',
  },
} as const

/**
 * 单一 token 源：颜色随 algorithm 派生，这里只定义品牌、
 * 中性表面与尺度；不再使用毛玻璃/渐变（统一实色分层）。
 */
export function buildThemeConfig(mode: ThemeMode): ThemeConfig {
  const dark = mode === 'dark'
  const s = dark ? SURFACE.dark : SURFACE.light

  return {
    algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    // 开启 CSS 变量模式：自定义 CSS 可直接引用 --ant-* 变量并自动跟随主题
    cssVar: { key: 'sa' },
    token: {
      colorPrimary: SAGE[500],
      colorPrimaryHover: dark ? '#63735f' : SAGE[600],
      colorPrimaryActive: SAGE[700],
      // 链接/强调文字在深色底上需要更高对比度，浅色底上则用更深的绿
      colorLink: dark ? SAGE[200] : SAGE[600],
      colorLinkHover: dark ? SAGE[300] : SAGE[500],

      colorBgLayout: s.layout,
      colorBgContainer: s.container,
      colorBgElevated: s.elevated,
      colorBorder: s.border,
      colorBorderSecondary: s.borderSecondary,
      colorFillTertiary: s.fill,

      borderRadius: 8,
      borderRadiusLG: 12,
      borderRadiusSM: 6,
      controlHeight: 34,
      fontSize: 14,
      fontFamily:
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
      wireframe: false,
    },
    components: {
      Layout: {
        // 侧栏/页头背景由自定义 CSS 控制，Layout 本身透明
        siderBg: 'transparent',
        lightSiderBg: 'transparent',
        headerBg: 'transparent',
        bodyBg: 'transparent',
      },
      Menu: {
        itemHeight: 38,
        itemMarginInline: 8,
        itemBorderRadius: 8,
        itemSelectedBg: dark ? 'rgba(82,94,84,0.30)' : 'rgba(82,94,84,0.12)',
        itemSelectedColor: dark ? SAGE[200] : SAGE[600],
        itemHoverBg: dark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
      },
      Button: {
        primaryShadow: 'none',
        defaultShadow: 'none',
        fontWeight: 500,
      },
      Card: {
        headerFontSize: 14,
        headerHeight: 48,
        paddingLG: 20,
      },
      Table: {
        headerBg: s.tableHeader,
        headerColor: dark ? '#c6ccc7' : '#4b5450',
        cellPaddingBlock: 10,
      },
      Tabs: {
        horizontalItemPadding: '10px 0',
      },
    },
  }
}
