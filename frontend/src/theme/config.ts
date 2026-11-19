import { theme } from 'antd'
import type { ThemeConfig } from 'antd'

/** 用户的主题偏好：跟随系统 / 固定浅色 / 固定深色。 */
export type ThemeMode = 'dark' | 'light' | 'system'
/** 解析后的实际主题（跟随系统后只可能是浅色或深色）。 */
export type ResolvedTheme = 'dark' | 'light'

export const THEME_STORAGE_KEY = 'self-agent.theme'

export const BRAND_NAME = '团队知识库助手智能体'
export const APP_VERSION = 'v0.1.0'

/** 布局尺寸（与 index.css 的 --ws-* 保持一致）。 */
export const LAYOUT = {
  sidebarWidth: 236,
  sidebarCollapsedWidth: 64,
  drawerWidth: 248,
} as const

/** 品牌主色：青绿（取自 self-web 的 accent 深色档，白字对比 ≈ 4.9:1）。 */
export const BRAND_PRIMARY = '#0f766e'

/**
 * 青绿色阶（对齐 self-web 的 accent 家族）。
 * 深色下按钮底仍用 600 档保证白字可读，文字/图标态用 300/400 的亮青。
 */
export const TEAL = {
  200: '#a7e8dc',
  300: '#8fe6d5',
  400: '#5fd8c0',
  500: '#14b8a6',
  600: '#0f766e',
  700: '#0b5f57',
} as const

/**
 * 中性表面：取 self-web 的「底色更绿、面板更青」双色关系，仍用实色分层
 * （不引入半透明与 backdrop-filter：本项目组件密度高，玻璃会让层与层互相串色）。
 *
 * 浅色：底色 #d0e2db（薄荷绿）< 面板 #f2f8f9（青白）< 浮层 #f7fbfc
 * 深色：底色 #0c1714（墨绿）< 面板 #1c2a30（青灰）< 抬升层 #22343b
 */
export const SURFACE = {
  light: {
    layout: '#d0e2db',
    container: '#f2f8f9',
    /* 浮层与输入框：比面板只亮一点点。原来 #f7fbfc 接近纯白，
       在薄荷底上会读成一块「贴上去的白纸」 */
    elevated: '#f4fafb',
    secondary: '#e5eef1',
    border: '#bfd4cf',
    borderSecondary: '#d6e4e0',
    fill: '#e8f1ef',
    tableHeader: '#e5eef1',
    text: '#162221',
    textSecondary: '#3f5656',
    textTertiary: '#465a5a',
    textQuaternary: '#6b7d7d',
  },
  dark: {
    layout: '#0c1714',
    container: '#1c2a30',
    elevated: '#22343b',
    secondary: '#22343b',
    border: '#2e4441',
    borderSecondary: '#243733',
    fill: '#22343b',
    tableHeader: '#1a262c',
    text: '#e8eded',
    textSecondary: '#b0c4c4',
    textTertiary: '#93a9aa',
    textQuaternary: '#6b8080',
  },
} as const

/**
 * 低饱和状态色（品牌化，替代 antd 固定色盘）。
 * antd 会据此派生 *-bg / *-border，供 Alert / Tag(success…) / Badge 等使用；
 * 固定色盘（green/red/blue/orange/volcano…）由 index.css 统一映射到这些变量。
 */
export const STATUS = {
  light: {
    success: '#0f766e',
    warning: '#b45309',
    error: '#b91c1c',
    info: '#0e7490',
  },
  dark: {
    success: '#6ee7b7',
    warning: '#fbbf24',
    error: '#f87171',
    info: '#7dd3fc',
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
export function buildThemeConfig(mode: ResolvedTheme): ThemeConfig {
  const dark = mode === 'dark'
  const s = dark ? SURFACE.dark : SURFACE.light
  const st = dark ? STATUS.dark : STATUS.light

  return {
    algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    // 开启 CSS 变量模式：自定义 CSS 可直接引用 --ant-* 变量并自动跟随主题
    cssVar: { key: 'sa' },
    token: {
      // --- 品牌 ---
      colorPrimary: TEAL[600],
      colorPrimaryHover: dark ? '#129184' : TEAL[700],
      colorPrimaryActive: TEAL[700],
      colorLink: dark ? TEAL[400] : TEAL[700],
      colorLinkHover: dark ? TEAL[300] : TEAL[600],
      colorLinkActive: TEAL[700],

      // 主色派生色必须显式指定：antd 由 #0f766e 自动算出的是 #a8b5b2（中灰绿），
      // 用作选中底/卡片底会脏掉——浅色下发灰突兀，深色下又不够亮。
      colorPrimaryBg: dark ? 'rgba(95, 209, 181, 0.14)' : '#e6f2f0',
      colorPrimaryBgHover: dark ? 'rgba(95, 209, 181, 0.24)' : '#d9ebe8',
      colorPrimaryBorder: dark ? 'rgba(95, 209, 181, 0.40)' : '#b3d9d2',
      colorPrimaryBorderHover: dark ? 'rgba(95, 209, 181, 0.58)' : '#8fc8bf',
      colorPrimaryText: dark ? TEAL[300] : TEAL[700],
      colorPrimaryTextHover: dark ? TEAL[200] : TEAL[600],

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
      // 次级表面（Secondary Surface）：用于次级底/条带，随主题切换
      colorFillQuaternary: s.secondary,

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
      boxShadow: dark ? '0 1px 2px rgba(0, 0, 0, 0.35)' : '0 1px 2px rgba(16, 24, 40, 0.05)',
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
        itemSelectedBg: dark ? 'rgba(95, 209, 181, 0.14)' : 'rgba(15, 118, 110, 0.10)',
        itemSelectedColor: dark ? TEAL[300] : TEAL[700],
        itemHoverBg: dark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(15, 118, 110, 0.06)',
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
      // 输入类控件比卡片再浅一档，避免奶油底上的输入框"消失"（仍有描边兜底）
      Input: { colorBgContainer: s.elevated },
      Select: { colorBgContainer: s.elevated },
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
