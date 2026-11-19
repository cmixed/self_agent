import type { PageKey } from './state/nav'

/**
 * 全局快捷键的**单一事实来源**，键位与 self-web 保持一致：
 *
 * - 只用**裸键**与 **G 开头的序列键**，不抢 Ctrl / ⌘ / Alt（浏览器与系统习惯留给用户）；
 * - `?` / F1 打开帮助，`/` 搜索，`T` 切主题，`G` 后接字母跳页；
 * - 焦点在输入框 / 输入法组合中一律不响应，中文输入不会吞字；
 * - 中文输入法下 `?`、`/` 会发成全角，匹配前统一折回半角。
 */

export type HotkeyGroup = '通用' | '导航' | '当前页面'

/** 帮助面板中的分组顺序 */
export const HOTKEY_GROUPS: HotkeyGroup[] = ['通用', '导航', '当前页面']

export interface HotkeyDef {
  id: string
  /** 单个键（`t`、`/`、`?`、`f1`），或空格分隔的序列（`g w`） */
  combo: string
  /** 等价按键：同一个动作有多个入口时并列展示与匹配 */
  aliases?: string[]
  title: string
  group: HotkeyGroup
  /** 仅在该页面生效；不填表示全局 */
  scope?: PageKey
  description?: string
  /** 是否允许在输入框聚焦时触发，默认仅 escape 允许 */
  allowInInput?: boolean
  /** 只展示不注册全局监听：由控件自身处理（如输入框的 Enter） */
  displayOnly?: boolean
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

/** 侧栏顺序与 PAGE_META 一致；G 序列按这个表生成 */
export const PAGE_ORDER = Object.keys(PAGE_LABELS) as PageKey[]

/** G 后面接的那个字母（序列键不会与单键 T 冲突，只取易记的） */
export const PAGE_KEYS: Record<PageKey, string> = {
  workspace: 'w',
  knowledge: 'k',
  presets: 'r',
  history: 'h',
  skills: 's',
  memory: 'm',
  team: 'e',
  providers: 'p',
  settings: ',',
}

const BASE_HOTKEYS: HotkeyDef[] = [
  {
    id: 'help',
    combo: '?',
    aliases: ['f1'],
    title: '显示快捷键帮助',
    group: '通用',
    description: 'F1 不用按 Shift，中文输入法下更稳',
  },
  {
    id: 'search',
    combo: '/',
    title: '全局搜索',
    group: '通用',
    description: '搜索页面、知识库与快捷键',
  },
  {
    id: 'toggleTheme',
    combo: 't',
    title: '切换深浅主题',
    group: '通用',
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
    combo: 'enter',
    title: '提交任务 / 换行',
    group: '当前页面',
    scope: 'workspace',
    description: '任务输入框内 Enter 提交，Shift+Enter 换行',
    displayOnly: true,
  },
]

/**
 * 按当前身份生成快捷键表：非管理员看不到「团队管理」，其余页面不受影响。
 * 帮助面板与运行时匹配读同一份结果，不会出现提示与实际不一致。
 */
export function hotkeysFor(isAdmin: boolean): HotkeyDef[] {
  const pages = PAGE_ORDER.filter((key) => isAdmin || key !== 'team')
  return [
    ...BASE_HOTKEYS,
    ...pages.map((key) => ({
      id: `page:${key}`,
      combo: `g ${PAGE_KEYS[key]}`,
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

/** `g w` 这类序列键 */
export function isSequence(combo: string): boolean {
  return combo.trim().includes(' ')
}

export function sequenceKeys(combo: string): string[] {
  return combo.trim().split(/\s+/)
}

/**
 * 中文输入法开启时，`?` / `/` 会发成全角字符，全角字母同理。
 * 全角 ASCII 区间 FF01–FF5E，减去 FEE0 即对应半角。
 */
export function normalizeKey(raw: string): string {
  if (raw.length !== 1) return raw.toLowerCase()
  const code = raw.charCodeAt(0)
  if (code >= 0xff01 && code <= 0xff5e) {
    return String.fromCharCode(code - 0xfee0).toLowerCase()
  }
  return raw.toLowerCase()
}

export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false
  return /mac|iphone|ipad|ipod/i.test(navigator.platform || navigator.userAgent)
}

/** 判断按键事件是否命中某个单键 / 组合键（不含序列键） */
export function matchesCombo(event: KeyboardEvent, combo: string): boolean {
  if (isSequence(combo)) return false
  const parsed = parseCombo(combo)
  const mod = isMacPlatform() ? event.metaKey : event.ctrlKey
  const otherMod = isMacPlatform() ? event.ctrlKey : event.metaKey
  if (otherMod || mod !== parsed.mod) return false
  if (event.altKey !== parsed.alt) return false
  // 「?」在不同键盘布局上未必是 Shift+/，直接认最终字符，不检查 Shift 状态
  if (parsed.key === '?') return event.key === '?'
  if (event.shiftKey !== parsed.shift) return false
  return normalizeKey(event.key) === parsed.key
}

/** 一个动作可绑定多个等价按键，任意一个命中即触发 */
export function matchesHotkey(event: KeyboardEvent, def: HotkeyDef): boolean {
  return (
    matchesCombo(event, def.combo) ||
    (def.aliases ?? []).some((combo) => matchesCombo(event, combo))
  )
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
  f1: 'F1',
  '/': '/',
  '?': '?',
  ',': ',',
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

/** 帮助面板中的按键展示：序列键用「然后」，等价按键用「或」 */
export function formatHotkey(def: HotkeyDef): string {
  const formatOne = (combo: string) =>
    isSequence(combo)
      ? sequenceKeys(combo)
          .map((key) => formatCombo(key))
          .join(' 然后 ')
      : formatCombo(combo)
  return [def.combo, ...(def.aliases ?? [])].map(formatOne).join(' / ')
}
