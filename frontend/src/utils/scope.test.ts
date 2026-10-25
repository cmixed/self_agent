import { describe, expect, it } from 'vite-plus/test'

import type { CategoryInfo, DocumentInfo } from '../types/api'
import { describeScope } from './scope'

function category(id: string, name: string, documentCount = 0): CategoryInfo {
  return {
    category_id: id,
    name,
    description: '',
    document_count: documentCount,
    created_at: '2026-01-01T00:00:00+00:00',
    updated_at: '2026-01-01T00:00:00+00:00',
  }
}

function document(id: string, categoryIds: string[] = []): DocumentInfo {
  return {
    document_id: id,
    filename: `${id}.pdf`,
    title: id,
    chunks: 1,
    category_ids: categoryIds,
  }
}

describe('describeScope', () => {
  it('未绑定范围时展示全部知识库', () => {
    expect(describeScope(null, [], [])).toEqual({
      bound: false,
      documentCount: 0,
      invalid: false,
      label: '全部知识库',
    })
    expect(describeScope({ category_ids: [], document_ids: [] }, [], []).bound).toBe(false)
  })

  it('类别范围统计范围内文档数（包含后续新增的同类文档）', () => {
    const categories = [category('c1', 'RAG 专题')]
    const documents = [document('d1', ['c1']), document('d2', ['c1']), document('d3', ['c2'])]

    expect(
      describeScope({ category_ids: ['c1'], document_ids: [] }, categories, documents),
    ).toEqual({
      bound: true,
      documentCount: 2,
      invalid: false,
      label: 'RAG 专题（共 2 篇）',
    })
  })

  it('类别与单篇去重，不重复计数', () => {
    const categories = [category('c1', '论文')]
    const documents = [document('d1', ['c1']), document('d2', ['c1']), document('d3')]

    const described = describeScope(
      { category_ids: ['c1'], document_ids: ['d1', 'd3'] },
      categories,
      documents,
    )
    expect(described.documentCount).toBe(3)
    expect(described.label).toBe('论文 + 2 篇单独选择（共 3 篇）')
    expect(described.invalid).toBe(false)
  })

  it('类别名多于两个时折叠为数量', () => {
    const categories = [category('c1', 'A'), category('c2', 'B'), category('c3', 'C')]
    const documents = [document('d1', ['c1']), document('d2', ['c2']), document('d3', ['c3'])]

    expect(
      describeScope({ category_ids: ['c1', 'c2', 'c3'], document_ids: [] }, categories, documents)
        .label,
    ).toBe('3 个类别（共 3 篇）')
  })

  it('绑定了类别但范围内没有文档时标记为 invalid', () => {
    const described = describeScope(
      { category_ids: ['c1'], document_ids: [] },
      [category('c1', '空类别')],
      [],
    )
    expect(described).toEqual({
      bound: true,
      documentCount: 0,
      invalid: true,
      label: '空类别（共 0 篇）',
    })
  })

  it('类别已被删除时保留兜底文案', () => {
    const described = describeScope({ category_ids: ['gone'], document_ids: [] }, [], [])
    expect(described.label).toBe('指定范围（共 0 篇）')
    expect(described.invalid).toBe(true)
  })

  it('只选单篇文档时展示篇数', () => {
    const described = describeScope(
      { category_ids: [], document_ids: ['d1'] },
      [],
      [document('d1')],
    )
    expect(described.label).toBe('1 篇单独选择（共 1 篇）')
    expect(described.invalid).toBe(false)
  })
})
