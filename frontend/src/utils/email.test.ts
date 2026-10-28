import { describe, expect, it } from 'vite-plus/test'

import {
  EMAIL_RECIPIENT_STORAGE_KEY,
  isValidEmail,
  maskEmail,
  normalizeRecipient,
  readLastRecipient,
  saveLastRecipient,
} from './email'

function fakeStorage() {
  const data = new Map<string, string>()
  const storage = {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (key: string) => data.get(key) ?? null,
    key: (index: number) => [...data.keys()][index] ?? null,
    removeItem: (key: string) => {
      data.delete(key)
    },
    setItem: (key: string, value: string) => {
      data.set(key, value)
    },
    data,
  }
  return storage
}

describe('email helpers', () => {
  it('归一化域名并保留本地部分大小写', () => {
    expect(normalizeRecipient('  User@Example.COM ')).toBe('User@example.com')
  })

  it('校验常见地址并拒绝空值 / 换行 / 非法格式', () => {
    expect(isValidEmail('reader@example.com')).toBe(true)
    expect(isValidEmail('first.last+tag@sub.example.co')).toBe(true)
    expect(isValidEmail('')).toBe(false)
    expect(isValidEmail('not-an-email')).toBe(false)
    expect(isValidEmail('a@b')).toBe(false)
    expect(isValidEmail('a@b.com\nBcc: x@y.com')).toBe(false)
    expect(isValidEmail(`${'a'.repeat(65)}@example.com`)).toBe(false)
  })

  it('脱敏只保留首字符与域名', () => {
    expect(maskEmail('reader@example.com')).toBe('r***@example.com')
    expect(maskEmail('bad')).toBe('***')
  })

  it('记住上次成功使用的收件人', () => {
    const storage = fakeStorage()
    saveLastRecipient(' Reader@Example.com ', storage)
    expect(storage.data.get(EMAIL_RECIPIENT_STORAGE_KEY)).toBe('Reader@example.com')
    expect(readLastRecipient(storage)).toBe('Reader@example.com')
  })

  it('忽略损坏或非法的已存值', () => {
    const storage = fakeStorage()
    storage.setItem(EMAIL_RECIPIENT_STORAGE_KEY, 'broken')
    expect(readLastRecipient(storage)).toBe('')
    saveLastRecipient('broken', storage)
    expect(storage.data.get(EMAIL_RECIPIENT_STORAGE_KEY)).toBe('broken')
  })
})
