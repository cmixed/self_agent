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
 * 采用 `checkStrictly`（父子独立勾选），语义清晰且与后端协议一一对应：
 * - 勾选**类别** = 整个类别（后端按类别解析）；
 * - 单独勾选**文档** = 只加这一篇（未分类文档只能这样选）；
 * - 两者可叠加（后端取并集）；都不勾 = 全部知识库。
 */
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
    setCheckedKeys([
      ...value.category_ids.map((id) => `cat:${id}`),
      ...value.document_ids.map((id) => `doc:${id}`),
    ])
  }, [open, value])

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
    const keys = checkedKeys.map(String)
    onConfirm({
      category_ids: keys.filter((key) => key.startsWith('cat:')).map((key) => key.slice(4)),
      document_ids: keys.filter((key) => key.startsWith('doc:')).map((key) => key.slice(4)),
    })
  }

  const selectedCategories = checkedKeys.filter((key) => String(key).startsWith('cat:')).length
  const selectedDocuments = checkedKeys.filter((key) => String(key).startsWith('doc:')).length

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
          勾选类别表示整个类别；只想用某一篇时单独勾选该文档。什么都不勾 = 使用全部知识库。
        </Text>
        {treeData.length === 0 ? (
          <Text type="secondary">知识库还没有文档，先去「知识库」上传并分类。</Text>
        ) : (
          <Tree
            checkable
            selectable={false}
            checkStrictly
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
          已选：{selectedCategories} 个类别、{selectedDocuments} 篇文档
        </Text>
      </Space>
    </Modal>
  )
}
