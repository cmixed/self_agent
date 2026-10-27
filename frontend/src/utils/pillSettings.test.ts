import { describe, expect, it } from 'vite-plus/test'

import {
  clampPillSettings,
  DEFAULT_PILL_SETTINGS,
  PILL_SETTINGS_STORAGE_KEY,
  readPillSettings,
  writePillSettings,
} from './pillSettings'

function fakeStorage() {
  const data = new Map<string, string>()
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
  }
}

describe('clampPillSettings', () => {
  it('缺省 / 非法值回退默认值', () => {
    expect(clampPillSettings(null)).toEqual(DEFAULT_PILL_SETTINGS)
    expect(clampPillSettings({})).toEqual(DEFAULT_PILL_SETTINGS)
    expect(clampPillSettings({ pendingLimit: 'x', restoreLimit: Number.NaN })).toEqual(
      DEFAULT_PILL_SETTINGS,
    )
  })

  it('越界值夹到范围内并取整', () => {
    expect(
      clampPillSettings({ pendingLimit: 0, restoreWindowHours: 999, restoreLimit: 2.6 }),
    ).toEqual({ pendingLimit: 1, restoreWindowHours: 168, restoreLimit: 3 })
  })
})

describe('胶囊设置的读写', () => {
  it('写入后读回，且写入前先夹取', () => {
    const storage = fakeStorage()
    const saved = writePillSettings(
      { pendingLimit: 50, restoreWindowHours: 2, restoreLimit: -1 },
      storage,
    )
    expect(saved).toEqual({ pendingLimit: 20, restoreWindowHours: 2, restoreLimit: 1 })
    expect(readPillSettings(storage)).toEqual(saved)
    expect(storage.data.has(PILL_SETTINGS_STORAGE_KEY)).toBe(true)
  })

  it('缺失 / 损坏时回退默认值', () => {
    const storage = fakeStorage()
    expect(readPillSettings(storage)).toEqual(DEFAULT_PILL_SETTINGS)

    storage.setItem(PILL_SETTINGS_STORAGE_KEY, 'not-json')
    expect(readPillSettings(storage)).toEqual(DEFAULT_PILL_SETTINGS)

    expect(readPillSettings(null)).toEqual(DEFAULT_PILL_SETTINGS)
  })
})
