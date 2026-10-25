import { describe, expect, it } from 'vite-plus/test'

import type { TokenUsage } from '../types/api'
import {
  cacheHitRate,
  documentKind,
  formatDateTime,
  formatDuration,
  formatTokenRate,
  formatTokens,
  taskDurationSeconds,
} from './format'

function usage(overrides: Partial<TokenUsage> = {}): TokenUsage {
  return {
    calls: 1,
    prompt_tokens: 100,
    completion_tokens: 10,
    total_tokens: 110,
    cache_hit_tokens: 0,
    cache_miss_tokens: 100,
    cache_reported: true,
    llm_seconds: 1,
    tokens_per_second: 10,
    models: ['test-model'],
    ...overrides,
  }
}

describe('formatDuration', () => {
  it('空值与非有限数返回占位符', () => {
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(undefined)).toBe('—')
    expect(formatDuration(Number.NaN)).toBe('—')
    expect(formatDuration(-1)).toBe('—')
  })

  it('小于一分钟按秒展示', () => {
    expect(formatDuration(0)).toBe('0s')
    expect(formatDuration(5.4)).toBe('5s')
  })

  it('分钟与秒组合，整分钟省略秒', () => {
    expect(formatDuration(90)).toBe('1m 30s')
    expect(formatDuration(120)).toBe('2m')
    expect(formatDuration(3600)).toBe('60m')
  })
})

describe('taskDurationSeconds', () => {
  it('用起止时间计算秒数', () => {
    expect(taskDurationSeconds('2026-01-01T00:00:00+00:00', '2026-01-01T00:01:30+00:00')).toBe(90)
  })

  it('缺失或非法时间返回 null', () => {
    expect(taskDurationSeconds(null, '2026-01-01T00:00:00Z')).toBeNull()
    expect(taskDurationSeconds('2026-01-01T00:00:00Z', null)).toBeNull()
    expect(taskDurationSeconds('not-a-date', '2026-01-01T00:00:00Z')).toBeNull()
  })

  it('结束时间早于开始时间时收敛为 0', () => {
    expect(taskDurationSeconds('2026-01-01T00:02:00+00:00', '2026-01-01T00:01:00+00:00')).toBe(0)
  })
})

describe('formatDateTime', () => {
  it('空值返回占位符', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime('')).toBe('—')
  })

  it('去掉 ISO 的 T、Z 与 UTC 后缀', () => {
    expect(formatDateTime('2026-01-02T03:04:05Z')).toBe('2026-01-02 03:04:05')
    expect(formatDateTime('2026-01-02T03:04:05+00:00')).toBe('2026-01-02 03:04:05')
  })
})

describe('formatTokens', () => {
  it('空值与负数返回占位符', () => {
    expect(formatTokens(null)).toBe('—')
    expect(formatTokens(-1)).toBe('—')
  })

  it('按量级切换单位与精度', () => {
    expect(formatTokens(999)).toBe('999')
    expect(formatTokens(1500)).toBe('1.5k')
    expect(formatTokens(12_345)).toBe('12k')
    expect(formatTokens(1_500_000)).toBe('1.5M')
  })
})

describe('formatTokenRate', () => {
  it('非法值返回占位符', () => {
    expect(formatTokenRate(null)).toBe('—')
    expect(formatTokenRate(0)).toBe('—')
  })

  it('低速保留一位小数，高速取整', () => {
    expect(formatTokenRate(12.34)).toBe('12.3 tok/s')
    expect(formatTokenRate(120)).toBe('120 tok/s')
  })
})

describe('cacheHitRate', () => {
  it('未上报缓存或没有 prompt token 时返回 null', () => {
    expect(cacheHitRate(null)).toBeNull()
    expect(cacheHitRate(usage({ cache_reported: false, cache_hit_tokens: 50 }))).toBeNull()
    expect(cacheHitRate(usage({ prompt_tokens: 0, cache_hit_tokens: 0 }))).toBeNull()
  })

  it('按 prompt token 计算命中率', () => {
    expect(cacheHitRate(usage({ prompt_tokens: 200, cache_hit_tokens: 50 }))).toBe(0.25)
  })
})

describe('documentKind', () => {
  it('按扩展名识别，大小写不敏感', () => {
    expect(documentKind('paper.PDF')).toBe('pdf')
    expect(documentKind('notes.md')).toBe('markdown')
    expect(documentKind('notes.markdown')).toBe('markdown')
    expect(documentKind('notes.txt')).toBe('text')
    expect(documentKind('archive.docx')).toBe('unknown')
  })
})
