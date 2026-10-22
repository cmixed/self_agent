import { Modal, Space, Tree, Typography } from 'antd'
import type { TreeDataNode } from 'antd'
import { useEffect, useMemo, useState } from 'react'

import type { CategoryInfo, DocumentInfo } from '../types/api'

const { Text } = Typography

/** 未分类文档的伪父节点 key（无法通过类别选中，只能逐篇选） */
const UNCLASSIFIED_KEY = '__unclassified__'

export interface ScopeSelection {
  category_ids: string[]
  document_ids: string[]
}

interface ScopePickerProps {
  open: boolean
  categories: CategoryInfo[]
  documents: DocumentInfo[]
  value: ScopeSelection
  onCancel: () => void
  onConfirm: (selection: ScopeSelection) => void
}

/**
 * 任务检索范围选择器。
 *
 * 采用**级联勾选**：勾选类别时其下所有文档一并勾选（能直接看到包含哪些文件），
 * 取消其中某篇则类别变为半选。
 *
 * 提交时再回推成后端协议：
 * - 完全勾选的类别 → `category_ids`（保留"整类"语义，重跑时新加入的文档会被纳入）；
 * - 未被已选类别覆盖的文档 → `document_ids`（单篇选择 / 未分类文档）；
 * - 都不勾 = 全部知识库。
 */

/** 由勾选状态回推后端协议（纯函数，便于审阅）。 */
export function deriveSelection(checkedKeys: string[], documents: DocumentInfo[]): ScopeSelection {
  const checkedCategoryIds = checkedKeys
    .filter((key) => key.startsWith('cat:'))
    .map((key) => key.slice(4))
  const checkedDocumentIds = new Set(
    checkedKeys.filter((key) => key.startsWith('doc:')).map((key) => key.slice(4)),
  )

  const selectedCategories = new Set(checkedCategoryIds)
  // 已被"整类"覆盖的文档不再重复计入 document_ids（后端取并集，这里保持精确）
  const covered = new Set<string>()
  for (const document of documents) {
    const ids = document.category_ids ?? []
    if (ids.some((id) => selectedCategories.has(id))) {
      covered.add(document.document_id)
    }
  }

  return {
    category_ids: checkedCategoryIds,
    document_ids: [...checkedDocumentIds].filter((id) => !covered.has(id)),
  }
}
export default function ScopePicker({
  open,
  categories,
  documents,
  value,
  onCancel,
  onConfirm,
}: ScopePickerProps) {
  const [checkedKeys, setCheckedKeys] = useState<React.Key[]>([])

  useEffect(() => {
    if (!open) return
    const keys = new Set<string>([
      ...value.category_ids.map((id) => `cat:${id}`),
      ...value.document_ids.map((id) => `doc:${id}`),
    ])
    // 级联显示：整类被选中时，其下文档也要呈勾选态
    for (const document of documents) {
      if ((document.category_ids ?? []).some((id) => value.category_ids.includes(id))) {
        keys.add(`doc:${document.document_id}`)
      }
    }
    setCheckedKeys([...keys])
  }, [open, value, documents])

  const treeData = useMemo<TreeDataNode[]>(() => {
    const byCategory = new Map<string, DocumentInfo[]>()
    const unclassified: DocumentInfo[] = []
    for (const document of documents) {
      const ids = document.category_ids ?? []
      if (ids.length === 0) {
        unclassified.push(document)
        continue
      }
      for (const categoryId of ids) {
        const bucket = byCategory.get(categoryId) ?? []
        bucket.push(document)
        byCategory.set(categoryId, bucket)
      }
    }

    const nodes: TreeDataNode[] = categories.map((category) => {
      const items = byCategory.get(category.category_id) ?? []
      return {
        key: `cat:${category.category_id}`,
        title: `${category.name}（${items.length} 篇）`,
        children: items.map((document) => ({
          key: `doc:${document.document_id}`,
          title: document.filename,
          isLeaf: true,
        })),
      }
    })

    if (unclassified.length > 0) {
      nodes.push({
        key: UNCLASSIFIED_KEY,
        title: `未分类文档（${unclassified.length} 篇）`,
        children: unclassified.map((document) => ({
          key: `doc:${document.document_id}`,
          title: document.filename,
          isLeaf: true,
        })),
      })
    }
    return nodes
  }, [categories, documents])

  const handleConfirm = () => {
    onConfirm(deriveSelection(checkedKeys.map(String), documents))
  }

  const selection = useMemo(
    () => deriveSelection(checkedKeys.map(String), documents),
    [checkedKeys, documents],
  )
  const selectedCategories = selection.category_ids.length
  const selectedDocuments = selection.document_ids.length
  const coveredDocuments = documents.filter((document) =>
    (document.category_ids ?? []).some((id) => selection.category_ids.includes(id)),
  ).length
  const effectiveDocuments = coveredDocuments + selectedDocuments

  return (
    <Modal
      title="选择知识库范围"
      open={open}
      onCancel={onCancel}
      onOk={handleConfirm}
      okText="确定"
      cancelText="取消"
      width={560}
      destroyOnHidden
    >
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Text type="secondary">
          勾选类别会连同其下所有文档一起选中（可再单独取消某篇）；只选个别文件时直接展开勾选。
          什么都不勾 = 使用全部知识库。
        </Text>
        {treeData.length === 0 ? (
          <Text type="secondary">知识库还没有文档，先去「知识库」上传并分类。</Text>
        ) : (
          <Tree
            checkable
            selectable={false}
            defaultExpandAll
            treeData={treeData}
            checkedKeys={checkedKeys}
            onCheck={(keys) => {
              const list = Array.isArray(keys) ? keys : keys.checked
              setCheckedKeys(list)
            }}
          />
        )}
        <Text type="secondary">
          已选：{selectedCategories > 0 ? `${selectedCategories} 个类别、` : ''}
          {selectedDocuments} 篇单独选择的文档
          {effectiveDocuments > 0 ? `（共涉及 ${effectiveDocuments} 篇）` : ''}
        </Text>
      </Space>
    </Modal>
  )
}
