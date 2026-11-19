import { describe, expect, it } from 'vite-plus/test'

import {
  HOTKEYS,
  formatCombo,
  formatHotkey,
  hotkeysFor,
  matchesCombo,
  matchesHotkey,
  parseCombo,
} from './hotkeys'

function keyEvent(init: Partial<KeyboardEvent> = {}): KeyboardEvent {
  return {
    key: '',
    code: '',
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    altKey: false,
    repeat: false,
    ...init,
  } as KeyboardEvent
}

describe('parseCombo', () => {
  it('解析 mod / shift 与主键', () => {
    expect(parseCombo('mod+shift+d')).toEqual({
      mod: true,
      shift: true,
      alt: false,
      key: 'd',
    })
  })

  it('解析符号键与方向键', () => {
    expect(parseCombo('mod+/').key).toBe('/')
    expect(parseCombo('mod+arrowleft').key).toBe('arrowleft')
    expect(parseCombo('escape').mod).toBe(false)
  })
})

describe('matchesCombo', () => {
  it('mod 在非 macOS 上映射为 Ctrl', () => {
    expect(matchesCombo(keyEvent({ key: '/', ctrlKey: true }), 'mod+/')).toBe(true)
    expect(matchesCombo(keyEvent({ key: '/', metaKey: true }), 'mod+/')).toBe(false)
  })

  it('修饰键必须完全匹配', () => {
    expect(matchesCombo(keyEvent({ key: 'D', ctrlKey: true, shiftKey: true }), 'mod+shift+d')).toBe(
      true,
    )
    expect(matchesCombo(keyEvent({ key: 'd', ctrlKey: true }), 'mod+shift+d')).toBe(false)
    expect(
      matchesCombo(
        keyEvent({ key: 'd', ctrlKey: true, shiftKey: true, altKey: true }),
        'mod+shift+d',
      ),
    ).toBe(false)
  })

  it('主键大小写不敏感', () => {
    expect(matchesCombo(keyEvent({ key: '1', ctrlKey: true }), 'mod+1')).toBe(true)
    expect(matchesCombo(keyEvent({ key: 'Escape' }), 'escape')).toBe(true)
  })
})

describe('formatCombo', () => {
  it('macOS 用符号紧凑写法', () => {
    expect(formatCombo('mod+shift+d', true)).toBe('⌘⇧D')
    expect(formatCombo('mod+1', true)).toBe('⌘1')
    expect(formatCombo('mod+arrowright', true)).toBe('⌘→')
  })

  it('其它平台用 + 连接', () => {
    expect(formatCombo('mod+shift+d', false)).toBe('Ctrl+Shift+D')
    expect(formatCombo('mod+/', false)).toBe('Ctrl+/')
    expect(formatCombo('escape', false)).toBe('Esc')
  })
})

describe('HOTKEYS 元数据', () => {
  it('id 唯一且都能解析出主键', () => {
    const ids = HOTKEYS.map((item) => item.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const item of HOTKEYS) {
      expect(parseCombo(item.combo).key).not.toBe('')
      expect(item.title).not.toBe('')
    }
  })

  it('九个页面都有数字键跳转', () => {
    expect(HOTKEYS.filter((item) => item.id.startsWith('page:'))).toHaveLength(9)
  })

  it('非管理员不显示团队管理，后续数字键顺延', () => {
    const member = hotkeysFor(false)
    expect(member.some((item) => item.id === 'page:team')).toBe(false)
    expect(member.find((item) => item.id === 'page:providers')?.combo).toBe('mod+7')
    expect(member.find((item) => item.id === 'page:settings')?.combo).toBe('mod+8')
  })
})

describe('帮助 / 搜索 / 提交按键', () => {
  const help = HOTKEYS.find((item) => item.id === 'help')!
  const search = HOTKEYS.find((item) => item.id === 'search')!
  const submit = HOTKEYS.find((item) => item.id === 'task.submit')!

  it('? 与 F1 都能打开帮助，Ctrl+/ 不再占用', () => {
    expect(help.combo).toBe('?')
    expect(help.aliases).toContain('f1')
    expect(matchesHotkey(keyEvent({ key: '?', shiftKey: true }), help)).toBe(true)
    expect(matchesHotkey(keyEvent({ key: 'F1' }), help)).toBe(true)
    expect(matchesHotkey(keyEvent({ key: '/', ctrlKey: true }), help)).toBe(false)
    expect(formatHotkey(help)).toBe('? / F1')
  })

  it('/ 留给搜索，输入框内仍可正常输入', () => {
    expect(search.combo).toBe('/')
    expect(matchesCombo(keyEvent({ key: '/' }), '/')).toBe(true)
  })

  it('Enter 提交仅作说明，由输入框自身处理（Shift+Enter 换行）', () => {
    expect(submit.combo).toBe('enter')
    expect(submit.displayOnly).toBe(true)
    expect(submit.description).toContain('Shift+Enter')
  })
})
