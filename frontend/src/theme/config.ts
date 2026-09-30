import { theme } from 'antd'
import type { ThemeConfig } from 'antd'

export type ThemeMode = 'dark' | 'light'

export const THEME_STORAGE_KEY = 'self-agent.theme'

export const BRAND_NAME = '个人知识库任务型智能体'
export const BRAND_SUBTITLE = 'RAG Agent Workspace'
export const APP_VERSION = 'v0.1.0'

/** 布局尺寸（与 index.css 的 --ws-* 保持一致）。 */
export const LAYOUT = {
  sidebarWidth: 236,
  sidebarCollapsedWidth: 64,
  drawerWidth: 248,
} as const

/** 品牌主色：仙茶绿。浅色/深色共用同一主色。 */
export const BRAND_PRIMARY = '#525e54'

/**
 * 仙茶绿色阶（低饱和）。
 * 主色 #525e54 作为按钮底/描边够用（白字对比 ≈ 6.7:1）；
 * 深色底上作文字/图标对比不足，因此文字态使用更亮的 200/300。
 */
export const SAGE = {
  200: '#a7b3a7',
  300: '#8d9c8d',
  400: '#6b7a6b',
  500: '#525e54',
  600: '#475349',
  700: '#3c473e',
} as const

/** 中性表面：统一实色分层（无渐变 / 无毛玻璃 / 无发光）。 */
export const SURFACE = {
  light: {
    layout: '#f0e9df',
    container: '#ffffff',
    elevated: '#ffffff',
    border: '#e6ddcd',
    borderSecondary: '#efe8db',
    fill: '#f6f1e8',
    tableHeader: '#f7f3ec',
    text: '#1f2320',
    textSecondary: '#5b625c',
    textTertiary: '#8b928c',
    textQuaternary: '#a9aea8',
  },
  dark: {
    layout: '#101311',
    container: '#171a18',
    elevated: '#1d211e',
    border: '#2a302b',
    borderSecondary: '#212620',
    fill: '#1d211e',
    tableHeader: '#1b1f1c',
    text: '#e8ebe8',
    textSecondary: '#9da59e',
    textTertiary: '#6f776f',
    textQuaternary: '#565d56',
  },
} as const

/**
 * 低饱和状态色（品牌化，替代 antd 固定色盘）。
 * antd 会据此派生 *-bg / *-border，供 Alert / Tag(success…) / Badge 等使用；
 * 固定色盘（green/red/blue/orange/volcano…）由 index.css 统一映射到这些变量。
 */
export const STATUS = {
  light: {
    success: '#3f6b4a',
    warning: '#8a6a2f',
    error: '#a04942',
    info: '#475349',
  },
  dark: {
    success: '#8fb99a',
    warning: '#cbb173',
    error: '#d99b94',
    info: '#a7b3a7',
  },
} as const

/** 圆角（克制：6 / 8 / 12）。 */
export const RADIUS = { sm: 6, md: 8, lg: 12 } as const

/** 紧凑尺寸。 */
export const SIZES = { controlHeight: 34, controlHeightSM: 28, controlHeightLG: 40 } as const

/**
 * 单一 token 源：颜色全部在这里定义，业务组件只消费 antd 变量 / --ws-* 变量，
 * 不在页面里写死颜色。
 */
export function buildThemeConfig(mode: ThemeMode): ThemeConfig {
  const dark = mode === 'dark'
  const s = dark ? SURFACE.dark : SURFACE.light
  const st = dark ? STATUS.dark : STATUS.light

  return {
    algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    // 开启 CSS 变量模式：自定义 CSS 可直接引用 --ant-* 变量并自动跟随主题
    cssVar: { key: 'sa' },
    token: {
      // --- 品牌 ---
      colorPrimary: SAGE[500],
      colorPrimaryHover: dark ? '#63735f' : SAGE[600],
      colorPrimaryActive: SAGE[700],
      colorLink: dark ? SAGE[200] : SAGE[600],
      colorLinkHover: dark ? SAGE[300] : SAGE[500],
      colorLinkActive: SAGE[700],

      // --- 状态（低饱和） ---
      colorSuccess: st.success,
      colorWarning: st.warning,
      colorError: st.error,
      colorInfo: st.info,

      // --- 表面 / 边框 ---
      colorBgLayout: s.layout,
      colorBgContainer: s.container,
      colorBgElevated: s.elevated,
      colorBorder: s.border,
      colorBorderSecondary: s.borderSecondary,
      colorFillTertiary: s.fill,

      // --- 文字 ---
      colorText: s.text,
      colorTextSecondary: s.textSecondary,
      colorTextTertiary: s.textTertiary,
      colorTextQuaternary: s.textQuaternary,

      // --- 尺度 ---
      borderRadius: RADIUS.md,
      borderRadiusLG: RADIUS.lg,
      borderRadiusSM: RADIUS.sm,
      controlHeight: SIZES.controlHeight,
      controlHeightSM: SIZES.controlHeightSM,
      controlHeightLG: SIZES.controlHeightLG,
      fontSize: 14,
      fontSizeHeading4: 20,
      fontFamily:
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",

      // --- 阴影（克制） ---
      boxShadow: dark
        ? '0 1px 2px rgba(0, 0, 0, 0.35)'
        : '0 1px 2px rgba(16, 24, 40, 0.05)',
      boxShadowSecondary: dark
        ? '0 6px 16px rgba(0, 0, 0, 0.45)'
        : '0 4px 12px rgba(16, 24, 40, 0.08)',

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
        itemBorderRadius: RADIUS.md,
        itemSelectedBg: dark ? 'rgba(82, 94, 84, 0.32)' : 'rgba(82, 94, 84, 0.13)',
        itemSelectedColor: dark ? SAGE[200] : SAGE[600],
        itemHoverBg: dark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(31, 35, 32, 0.04)',
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
        headerColor: s.textSecondary,
        cellPaddingBlock: 10,
      },
      Tabs: {
        horizontalItemPadding: '10px 0',
      },
    },
  }
}
