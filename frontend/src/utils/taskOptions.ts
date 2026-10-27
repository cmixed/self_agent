/**
 * 「记住执行选项」的纯逻辑（便于单测，不依赖 React）。
 *
 * 存储位置刻意选 localStorage 而不是 SQLite `user_preferences`：
 * 偏好表存的是写作风格 / 输出格式等长期记忆，混入表单交互状态会污染记忆去重。
 *
 * 数据模型是「值 + 开关」：工作台每次实际使用都会记录最后一组选项，
 * 开关只决定进入工作台时是否自动套用。因此关闭再打开仍能回到上次的选择。
 */

import type { CategoryInfo, DocumentInfo, TaskDepth, TaskScope } from '../types/api'

export const TASK_OPTIONS_STORAGE_KEY = 'agent.taskOptions'
const STORAGE_VERSION = 1

const DEPTHS: readonly TaskDepth[] = ['auto', 'brief', 'longform']

export interface TaskOptions {
  depth: TaskDepth
  useSkills: boolean
  scope: TaskScope
}

/** 记住的选项 + 是否在进入工作台时自动套用。 */
export interface TaskOptionsMemory {
  remember: boolean
  options: TaskOptions
}

export const DEFAULT_TASK_OPTIONS: TaskOptions = {
  depth: 'auto',
  useSkills: false,
  scope: { category_ids: [], document_ids: [] },
}

export function defaultTaskOptionsMemory(): TaskOptionsMemory {
  return {
    remember: false,
    options: { ...DEFAULT_TASK_OPTIONS, scope: { category_ids: [], document_ids: [] } },
  }
}

type ReadableStorage = { getItem: (key: string) => string | null }
type WritableStorage = Pick<Storage, 'setItem' | 'removeItem'>
/** 读改写都需要的最小存储接口（localStorage 的子集，便于单测注入）。 */
type ReadWriteStorage = ReadableStorage & WritableStorage

function defaultStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    // 隐私模式等场景下 localStorage 不可用
    return null
  }
}

function idList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  for (const item of value) {
    if (typeof item === 'string' && item.trim()) seen.add(item)
  }
  return [...seen]
}

/** `brief` 不允许技能（与工作台表单的禁用规则一致）。 */
export function clampTaskOptions(options: TaskOptions): TaskOptions {
  return {
    depth: options.depth,
    useSkills: options.depth === 'brief' ? false : options.useSkills,
    scope: {
      category_ids: idList(options.scope?.category_ids),
      document_ids: idList(options.scope?.document_ids),
    },
  }
}

/** 校验并归一化外部数据；结构不合法返回 null（宁可回默认值也不套用脏数据）。 */
export function normalizeTaskOptions(raw: unknown): TaskOptions | null {
  if (!raw || typeof raw !== 'object') return null
  const data = raw as Record<string, unknown>
  if (!DEPTHS.includes(data.depth as TaskDepth)) return null
  const scope = (data.scope ?? {}) as Record<string, unknown>
  return clampTaskOptions({
    depth: data.depth as TaskDepth,
    useSkills: data.useSkills === true,
    scope: {
      category_ids: idList(scope.category_ids),
      document_ids: idList(scope.document_ids),
    },
  })
}

/** 读取记住的选项；缺失 / 损坏时回退默认值（开关关闭）。 */
export function readTaskOptionsMemory(
  storage: ReadableStorage | null = defaultStorage(),
): TaskOptionsMemory {
  try {
    const raw = storage?.getItem(TASK_OPTIONS_STORAGE_KEY)
    if (!raw) return defaultTaskOptionsMemory()
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return defaultTaskOptionsMemory()
    const data = parsed as Record<string, unknown>
    const options = normalizeTaskOptions(data)
    if (!options) return defaultTaskOptionsMemory()
    return { remember: data.remember === true, options }
  } catch {
    return defaultTaskOptionsMemory()
  }
}

/** 写入完整的记忆结构（开关 + 选项）。 */
export function writeTaskOptionsMemory(
  memory: TaskOptionsMemory,
  storage: WritableStorage | null = defaultStorage(),
): void {
  try {
    storage?.setItem(
      TASK_OPTIONS_STORAGE_KEY,
      JSON.stringify({
        version: STORAGE_VERSION,
        remember: memory.remember,
        ...clampTaskOptions(memory.options),
      }),
    )
  } catch {
    // 忽略写入失败：不影响本次使用
  }
}

/**
 * 记录「上一次实际使用」的选项，保留当前开关状态。
 *
 * 工作台在提交任务 / 开启记忆时调用；关闭记忆时也会照常记录，方便再次开启。
 */
export function saveTaskOptions(
  options: TaskOptions,
  storage: ReadWriteStorage | null = defaultStorage(),
): TaskOptionsMemory {
  const memory = readTaskOptionsMemory(storage)
  const next: TaskOptionsMemory = { remember: memory.remember, options: clampTaskOptions(options) }
  writeTaskOptionsMemory(next, storage)
  return next
}

/** 切换「记住上次的执行选项」；不清空已记录的选项值。 */
export function setTaskOptionsRemember(
  remember: boolean,
  storage: ReadWriteStorage | null = defaultStorage(),
): TaskOptionsMemory {
  const memory = readTaskOptionsMemory(storage)
  const next: TaskOptionsMemory = { remember, options: memory.options }
  writeTaskOptionsMemory(next, storage)
  return next
}

/** 清除记住的选项（开关同时回到关闭）。 */
export function clearTaskOptionsMemory(
  storage: Pick<Storage, 'removeItem'> | null = defaultStorage(),
): void {
  try {
    storage?.removeItem(TASK_OPTIONS_STORAGE_KEY)
  } catch {
    // 忽略清除失败
  }
}

/**
 * 剔除已删除的类别 / 文档，避免恢复出一个空范围或指向不存在的资料。
 *
 * 返回 `dropped` 供界面提示；调用方在「原本有范围、剔除后为空」时回退全部知识库。
 */
export function sanitizeScope(
  scope: TaskScope,
  categories: readonly Pick<CategoryInfo, 'category_id'>[],
  documents: readonly Pick<DocumentInfo, 'document_id'>[],
): { scope: TaskScope; dropped: number } {
  const categoryIds = new Set(categories.map((item) => item.category_id))
  const documentIds = new Set(documents.map((item) => item.document_id))
  const validCategories = scope.category_ids.filter((id) => categoryIds.has(id))
  const validDocuments = scope.document_ids.filter((id) => documentIds.has(id))
  const dropped =
    scope.category_ids.length -
    validCategories.length +
    (scope.document_ids.length - validDocuments.length)
  return {
    scope: { category_ids: validCategories, document_ids: validDocuments },
    dropped,
  }
}
