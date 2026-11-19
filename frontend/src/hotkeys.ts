import type { PageKey } from './state/nav'

/**
 * 全局快捷键的**单一事实来源**。
 *
 * 设计约束：
 * - 按键只在这里定义，帮助面板与运行时匹配都读同一份表，避免文档与实现漂移；
 * - `mod` 在 macOS 上映射到 ⌘、其它平台映射到 Ctrl，不写死平台键；
 * - 除 `escape` 外，输入框 / textarea / contenteditable 聚焦时一律不触发，
 *   否则用户打字会误操作（这也是带 mod 的组合键仍允许在输入框里用的原因）。
 */

export type HotkeyGroup = '通用' | '导航' | '界面' | '当前页面'

/** 帮助面板中的分组顺序 */
export const HOTKEY_GROUPS: HotkeyGroup[] = ['通用', '导航', '界面', '当前页面']

export interface HotkeyDef {
  id: string
  /** 组合键字符串：mod、shift、alt + 一个键名（如 `mod+/`、`mod+1`、`escape`） */
  combo: string
  title: string
  group: HotkeyGroup
  /** 仅在该页面生效；不填表示全局 */
  scope?: PageKey
  description?: string
  /** 是否允许在输入框聚焦时触发，默认仅 escape 允许 */
  allowInInput?: boolean
}

export const PAGE_LABELS: Record<PageKey, string> = {
  workspace: '工作台',
  knowledge: '知识库',
  presets: '预设任务',
  history: '任务历史',
  skills: '技能',
  memory: '长期记忆',
  team: '团队管理',
  providers: '模型服务',
  settings: '设置',
}

/** 侧栏顺序与 PAGE_META 一致；数字键跳转按这个顺序 */
export const PAGE_ORDER = Object.keys(PAGE_LABELS) as PageKey[]

/** 基础快捷键；页面数字键在下面按可见页面生成 */
const BASE_HOTKEYS: HotkeyDef[] = [
  {
    id: 'help',
    combo: 'mod+/',
    title: '显示快捷键帮助',
    group: '通用',
    description: '列出当前系统里所有可用快捷键',
  },
  {
    id: 'refresh',
    combo: 'mod+r',
    title: '刷新状态与当前页',
    group: '通用',
    description: '等同于左下角的刷新按钮',
  },
  {
    id: 'toggleTheme',
    combo: 'mod+shift+d',
    title: '切换深浅主题',
    group: '通用',
  },
  {
    id: 'toggleSidebar',
    combo: 'mod+shift+b',
    title: '折叠 / 展开侧栏',
    group: '界面',
    description: '窄屏下请用左上角菜单按钮',
  },
  {
    id: 'previousPage',
    combo: 'mod+arrowleft',
    title: '上一个页面',
    group: '导航',
  },
  {
    id: 'nextPage',
    combo: 'mod+arrowright',
    title: '下一个页面',
    group: '导航',
  },
  {
    id: 'goBack',
    combo: 'escape',
    title: '返回上一层',
    group: '导航',
    description: '关闭文档 / 任务详情等叠加视图；无叠加视图时不响应',
    allowInInput: true,
  },
  {
    id: 'task.submit',
    combo: 'mod+enter',
    title: '提交当前任务',
    group: '当前页面',
    scope: 'workspace',
    description: '等同于工作台的「开始任务」按钮',
  },
]

/**
 * 按当前身份生成快捷键表：非管理员看不到「团队管理」，数字键随之顺延，
 * 帮助面板与运行时匹配读同一份结果，不会出现「提示说 mod+7 是团队管理但按了没反应」。
 */
export function hotkeysFor(isAdmin: boolean): HotkeyDef[] {
  const pages = PAGE_ORDER.filter((key) => isAdmin || key !== 'team')
  return [
    ...BASE_HOTKEYS,
    ...pages.map((key, index) => ({
      id: `page:${key}`,
      combo: `mod+${index + 1}`,
      title: `跳转到${PAGE_LABELS[key]}`,
      group: '导航' as HotkeyGroup,
    })),
  ]
}

/** 管理员视角的全量快捷键，供不需要身份判断的场景使用 */
export const HOTKEYS = hotkeysFor(true)

export interface ParsedCombo {
  mod: boolean
  shift: boolean
  alt: boolean
  key: string
}

const MODIFIERS = new Set(['mod', 'shift', 'alt'])

export function parseCombo(combo: string): ParsedCombo {
  const parts = combo
    .toLowerCase()
    .split('+')
    .map((part) => part.trim())
  return {
    mod: parts.includes('mod'),
    shift: parts.includes('shift'),
    alt: parts.includes('alt'),
    key: parts.find((part) => part && !MODIFIERS.has(part)) ?? '',
  }
}

export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false
  return /mac|iphone|ipad|ipod/i.test(navigator.platform || navigator.userAgent)
}

/** 判断按键事件是否命中某个组合键 */
export function matchesCombo(event: KeyboardEvent, combo: string): boolean {
  const parsed = parseCombo(combo)
  // 用 metaKey 还是 ctrlKey 由平台决定，另一枚修饰键按下时不算命中
  const mod = isMacPlatform() ? event.metaKey : event.ctrlKey
  const otherMod = isMacPlatform() ? event.ctrlKey : event.metaKey
  if (otherMod || mod !== parsed.mod) return false
  if (event.shiftKey !== parsed.shift || event.altKey !== parsed.alt) return false
  return event.key.toLowerCase() === parsed.key
}

/** 输入框内打字时不响应单键快捷键；带 mod 的组合键仍可用 */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName.toLowerCase()
  return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable
}

const KEY_LABELS: Record<string, string> = {
  arrowleft: '←',
  arrowright: '→',
  arrowup: '↑',
  arrowdown: '↓',
  enter: 'Enter',
  escape: 'Esc',
  '/': '/',
}

/** 按平台渲染组合键：macOS 用符号紧凑写法，其它平台用 + 连接 */
export function formatCombo(combo: string, mac = isMacPlatform()): string {
  const { mod, shift, alt, key } = parseCombo(combo)
  const parts: string[] = []
  if (mod) parts.push(mac ? '⌘' : 'Ctrl')
  if (alt) parts.push(mac ? '⌥' : 'Alt')
  if (shift) parts.push(mac ? '⇧' : 'Shift')
  parts.push(KEY_LABELS[key] ?? (key.length === 1 ? key.toUpperCase() : key))
  return parts.join(mac ? '' : '+')
}
