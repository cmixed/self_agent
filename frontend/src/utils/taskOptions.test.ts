import { describe, expect, it } from 'vite-plus/test'

import type { CategoryInfo, DocumentInfo } from '../types/api'
import {
  clampTaskOptions,
  clearRememberedOptions,
  normalizeTaskOptions,
  readRememberedOptions,
  sanitizeScope,
  TASK_OPTIONS_STORAGE_KEY,
  writeRememberedOptions,
} from './taskOptions'

function fakeStorage() {
  const data = new Map<string, string>()
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  }
}

function category(id: string): CategoryInfo {
  return {
    category_id: id,
    name: id,
    description: '',
    document_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

function document(id: string): DocumentInfo {
  return {
    document_id: id,
    filename: `${id}.pdf`,
    title: id,
    chunks: 1,
    category_ids: [],
  }
}

describe('normalizeTaskOptions', () => {
  it('校验深度并归一化范围 id', () => {
    expect(
      normalizeTaskOptions({
        depth: 'longform',
        useSkills: true,
        scope: { category_ids: ['a', 'a', '', 1], document_ids: ['d'] },
      }),
    ).toEqual({
      depth: 'longform',
      useSkills: true,
      scope: { category_ids: ['a'], document_ids: ['d'] },
    })
  })

  it('简洁模式强制关闭技能', () => {
    expect(
      clampTaskOptions({
        depth: 'brief',
        useSkills: true,
        scope: { category_ids: [], document_ids: [] },
      }).useSkills,
    ).toBe(false)
  })

  it('深度非法或缺省时返回 null', () => {
    expect(normalizeTaskOptions(null)).toBeNull()
    expect(normalizeTaskOptions({ depth: 'deep' })).toBeNull()
  })
})

describe('记住选项的读写', () => {
  it('写入后可读回，关闭时清除', () => {
    const storage = fakeStorage()
    writeRememberedOptions(
      { depth: 'brief', useSkills: true, scope: { category_ids: ['c1'], document_ids: [] } },
      storage,
    )

    expect(readRememberedOptions(storage)).toEqual({
      depth: 'brief',
      useSkills: false,
      scope: { category_ids: ['c1'], document_ids: [] },
    })

    clearRememberedOptions(storage)
    expect(storage.data.has(TASK_OPTIONS_STORAGE_KEY)).toBe(false)
    expect(readRememberedOptions(storage)).toBeNull()
  })

  it('未开启 / 数据损坏时返回 null', () => {
    const storage = fakeStorage()
    storage.setItem(TASK_OPTIONS_STORAGE_KEY, JSON.stringify({ depth: 'auto' }))
    expect(readRememberedOptions(storage)).toBeNull()

    storage.setItem(TASK_OPTIONS_STORAGE_KEY, 'not-json')
    expect(readRememberedOptions(storage)).toBeNull()
    expect(readRememberedOptions(null)).toBeNull()
  })
})

describe('sanitizeScope', () => {
  it('剔除已删除的类别与文档，并统计数量', () => {
    const result = sanitizeScope(
      { category_ids: ['keep', 'gone'], document_ids: ['doc-keep', 'doc-gone'] },
      [category('keep')],
      [document('doc-keep')],
    )
    expect(result.scope).toEqual({ category_ids: ['keep'], document_ids: ['doc-keep'] })
    expect(result.dropped).toBe(2)
  })

  it('全部失效时返回空范围（由界面回退全部知识库）', () => {
    const result = sanitizeScope({ category_ids: ['gone'], document_ids: [] }, [], [])
    expect(result.scope).toEqual({ category_ids: [], document_ids: [] })
    expect(result.dropped).toBe(1)
  })
})
