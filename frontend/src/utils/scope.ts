import type { CategoryInfo, DocumentInfo, TaskScope } from '../types/api'

/** 检索范围的可读描述（工作台范围标签 / 预设范围徽标共用）。 */
export interface ScopeDescription {
  /** 是否绑定了范围（两者皆空 = 未绑定）。 */
  bound: boolean
  /** 范围内实际涉及的文档数（类别下的文档 + 单篇选择，去重）。 */
  documentCount: number
  /** 已绑定但一篇文档都没覆盖到（类别为空 / 文档已删）。 */
  invalid: boolean
  /** 展示用文案：未绑定为「全部知识库」，否则为组合摘要。 */
  label: string
}

/**
 * 把后端协议里的检索范围翻译成可读文案。
 *
 * - `scope` 为空或两个列表都空 = 未绑定 → `bound=false`，文案「全部知识库」；
 * - 绑定类别 = 整类（动态包含后续新增的文档），文案带类别名；
 * - 类别名多于两个时折叠为「N 个类别」，避免标签过长。
 */
export function describeScope(
  scope: TaskScope | null | undefined,
  categories: CategoryInfo[],
  documents: DocumentInfo[],
): ScopeDescription {
  const categoryIds = scope?.category_ids ?? []
  const documentIds = scope?.document_ids ?? []
  const bound = categoryIds.length + documentIds.length > 0

  const covered = new Set(documentIds)
  for (const document of documents) {
    if ((document.category_ids ?? []).some((id) => categoryIds.includes(id))) {
      covered.add(document.document_id)
    }
  }
  const documentCount = covered.size

  if (!bound) {
    return { bound: false, documentCount, invalid: false, label: '全部知识库' }
  }

  const names = categoryIds
    .map((id) => categories.find((item) => item.category_id === id)?.name)
    .filter((name): name is string => Boolean(name))
  const categoryLabel =
    names.length === 0 ? '' : names.length <= 2 ? names.join('、') : `${names.length} 个类别`
  const documentLabel = documentIds.length > 0 ? `${documentIds.length} 篇单独选择` : ''
  const parts = [categoryLabel, documentLabel].filter(Boolean).join(' + ')

  return {
    bound: true,
    documentCount,
    invalid: documentCount === 0,
    label: `${parts || '指定范围'}（共 ${documentCount} 篇）`,
  }
}
