import { describe, expect, it } from 'vite-plus/test'

import type { CategoryInfo, DocumentInfo } from '../types/api'
import {
  clearTaskOptionsMemory,
  clampTaskOptions,
  DEFAULT_TASK_OPTIONS,
  defaultTaskOptionsMemory,
  normalizeTaskOptions,
  readTaskOptionsMemory,
  sanitizeScope,
  saveTaskOptions,
  setTaskOptionsRemember,
  TASK_OPTIONS_STORAGE_KEY,
  writeTaskOptionsMemory,
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
      retrievalMode: 'selected',
      scope: { category_ids: ['a'], document_ids: ['d'] },
    })
  })

  it('简洁模式强制关闭技能', () => {
    expect(
      clampTaskOptions({
        depth: 'brief',
        useSkills: true,
        retrievalMode: 'all',
        scope: { category_ids: [], document_ids: [] },
      }).useSkills,
    ).toBe(false)
  })

  it('深度非法或缺省时返回 null', () => {
    expect(normalizeTaskOptions(null)).toBeNull()
    expect(normalizeTaskOptions({ depth: 'deep' })).toBeNull()
  })

  it('旧数据没有 retrievalMode 时按范围推断；显式 none 保留', () => {
    expect(
      normalizeTaskOptions({
        depth: 'auto',
        scope: { category_ids: [], document_ids: ['d1'] },
      })?.retrievalMode,
    ).toBe('selected')

    expect(
      normalizeTaskOptions({
        depth: 'brief',
        retrievalMode: 'none',
        scope: { category_ids: ['c1'], document_ids: [] },
      })?.retrievalMode,
    ).toBe('none')
  })
})

describe('执行选项记忆的读写', () => {
  it('缺失 / 损坏时回退默认值（开关关闭）', () => {
    const storage = fakeStorage()
    expect(readTaskOptionsMemory(storage)).toEqual(defaultTaskOptionsMemory())

    storage.setItem(TASK_OPTIONS_STORAGE_KEY, 'not-json')
    expect(readTaskOptionsMemory(storage)).toEqual(defaultTaskOptionsMemory())

    // 深度非法：整条记忆作废，而不是套用一半脏数据
    storage.setItem(TASK_OPTIONS_STORAGE_KEY, JSON.stringify({ depth: 'deep', remember: true }))
    expect(readTaskOptionsMemory(storage)).toEqual(defaultTaskOptionsMemory())

    expect(readTaskOptionsMemory(null)).toEqual(defaultTaskOptionsMemory())
  })

  it('写入后可读回，简洁模式不会记住技能', () => {
    const storage = fakeStorage()
    writeTaskOptionsMemory(
      {
        remember: true,
        options: {
          depth: 'brief',
          useSkills: true,
          retrievalMode: 'selected',
          scope: { category_ids: ['c1'], document_ids: ['d1'] },
        },
      },
      storage,
    )

    expect(readTaskOptionsMemory(storage)).toEqual({
      remember: true,
      options: {
        depth: 'brief',
        useSkills: false,
        retrievalMode: 'selected',
        scope: { category_ids: ['c1'], document_ids: ['d1'] },
      },
    })
  })

  it('关闭记忆只改开关，已记住的选项仍然保留', () => {
    const storage = fakeStorage()
    saveTaskOptions(
      {
        depth: 'longform',
        useSkills: true,
        retrievalMode: 'selected',
        scope: { category_ids: ['c1'], document_ids: [] },
      },
      storage,
    )

    const off = setTaskOptionsRemember(false, storage)
    expect(off.remember).toBe(false)
    expect(off.options.depth).toBe('longform')
    expect(off.options.useSkills).toBe(true)

    // 重新开启：回到上次选择，而不是默认值
    const on = setTaskOptionsRemember(true, storage)
    expect(on).toEqual({ remember: true, options: off.options })
    expect(readTaskOptionsMemory(storage).options).toEqual(off.options)
  })

  it('提交时记录「上一次实际使用」并保留开关状态', () => {
    const storage = fakeStorage()
    setTaskOptionsRemember(true, storage)

    const saved = saveTaskOptions(
      {
        depth: 'auto',
        useSkills: false,
        retrievalMode: 'all',
        scope: { category_ids: [], document_ids: ['d2'] },
      },
      storage,
    )
    expect(saved.remember).toBe(true)
    expect(saved.options.scope.document_ids).toEqual(['d2'])
    expect(readTaskOptionsMemory(storage)).toEqual(saved)
  })

  it('清除后回到默认值且移除存储键', () => {
    const storage = fakeStorage()
    saveTaskOptions(DEFAULT_TASK_OPTIONS, storage)
    expect(storage.data.has(TASK_OPTIONS_STORAGE_KEY)).toBe(true)

    clearTaskOptionsMemory(storage)
    expect(storage.data.has(TASK_OPTIONS_STORAGE_KEY)).toBe(false)
    expect(readTaskOptionsMemory(storage)).toEqual(defaultTaskOptionsMemory())
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
