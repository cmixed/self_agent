import { describe, expect, it } from 'vite-plus/test'

import {
  HOTKEYS,
  formatHotkey,
  hotkeysFor,
  isSequence,
  matchesCombo,
  matchesHotkey,
  normalizeKey,
  parseCombo,
  sequenceKeys,
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
  it('解析裸键与修饰键', () => {
    expect(parseCombo('t')).toEqual({ mod: false, shift: false, alt: false, key: 't' })
    expect(parseCombo('mod+shift+d')).toEqual({
      mod: true,
      shift: true,
      alt: false,
      key: 'd',
    })
  })
})

describe('matchesCombo', () => {
  it('裸键命中，带 Ctrl / ⌘ 时不命中（把组合键留给浏览器）', () => {
    expect(matchesCombo(keyEvent({ key: 't' }), 't')).toBe(true)
    expect(matchesCombo(keyEvent({ key: 't', ctrlKey: true }), 't')).toBe(false)
    expect(matchesCombo(keyEvent({ key: 't', metaKey: true }), 't')).toBe(false)
    expect(matchesCombo(keyEvent({ key: 'T' }), 't')).toBe(true)
  })

  it('? 忽略 Shift 状态，F1 大小写不敏感', () => {
    expect(matchesCombo(keyEvent({ key: '?', shiftKey: true }), '?')).toBe(true)
    expect(matchesCombo(keyEvent({ key: 'F1' }), 'f1')).toBe(true)
    expect(matchesCombo(keyEvent({ key: '/' }), '/')).toBe(true)
  })

  it('序列键不参与单键匹配', () => {
    expect(matchesCombo(keyEvent({ key: 'g' }), 'g w')).toBe(false)
  })
})

describe('序列键', () => {
  it('拆分前缀与第二键', () => {
    expect(isSequence('g w')).toBe(true)
    expect(isSequence('t')).toBe(false)
    expect(sequenceKeys('g w')).toEqual(['g', 'w'])
  })
})

describe('normalizeKey', () => {
  it('中文输入法下的全角字符折回半角', () => {
    expect(normalizeKey('？')).toBe('?')
    expect(normalizeKey('／')).toBe('/')
    expect(normalizeKey('Ｗ')).toBe('w')
    expect(normalizeKey('T')).toBe('t')
  })
})

describe('formatHotkey', () => {
  it('序列用「然后」，等价键用「或」', () => {
    const help = HOTKEYS.find((item) => item.id === 'help')!
    expect(formatHotkey(help)).toBe('? / F1')
    const page = HOTKEYS.find((item) => item.id === 'page:workspace')!
    expect(formatHotkey(page)).toBe('G 然后 W')
  })
})

describe('HOTKEYS 元数据', () => {
  it('id 唯一，且不占用 Ctrl / ⌘ / Alt', () => {
    const ids = HOTKEYS.map((item) => item.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const item of HOTKEYS) {
      expect(item.combo).not.toContain('mod')
      expect(item.title).not.toBe('')
    }
  })

  it('九个页面都用 G 序列跳转', () => {
    const pages = HOTKEYS.filter((item) => item.id.startsWith('page:'))
    expect(pages).toHaveLength(9)
    for (const page of pages) expect(isSequence(page.combo)).toBe(true)
  })

  it('非管理员不显示团队管理', () => {
    const member = hotkeysFor(false)
    expect(member.some((item) => item.id === 'page:team')).toBe(false)
    expect(member.filter((item) => item.id.startsWith('page:'))).toHaveLength(8)
  })

  it('帮助、搜索、主题与返回都在表内', () => {
    const byId = new Map(HOTKEYS.map((item) => [item.id, item]))
    expect(matchesHotkey(keyEvent({ key: '?' }), byId.get('help')!)).toBe(true)
    expect(matchesHotkey(keyEvent({ key: 'F1' }), byId.get('help')!)).toBe(true)
    expect(byId.get('search')?.combo).toBe('/')
    expect(byId.get('toggleTheme')?.combo).toBe('t')
    expect(byId.get('goBack')?.allowInInput).toBe(true)
  })
})
