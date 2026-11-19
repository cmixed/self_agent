import { Empty, Spin, Tooltip } from 'antd'
import { useMemo } from 'react'

import type { DocumentCaps, GraphEdge, GraphNode, ShareGraphData } from '../types/api'

/**
 * 共享关系图：人 / 组 / 知识库 三列布局。
 *
 * - 不引入力导向库：关系数量不大，固定三列反而更好读（谁 → 通过什么 → 访问哪个库）；
 * - 边的颜色表示授予的能力，虚线表示「待审批」；
 * - 关系多的时候只在悬停时看文字，避免标签互相压住。
 */

const NODE_W = 190
/** 分组节点要容纳「标题 / 人数 / 成员名单」三行，其余节点居中显示 */
const NODE_H = 62
/** 节点内直接展示的成员上限，超出的进 Tooltip 浮窗 */
const MEMBER_LIMIT = 2
const NODE_GAP = 14
const COL_GAP = 74
const PAD = 12
/** 顶部列标题（人 / 分组 / 知识库）占的高度 */
const HEAD = 26

const CAP_COLORS: Record<string, string> = {
  search: '#d48806',
  list: '#1677ff',
  read: '#389e0d',
  write: '#722ed1',
  pending: '#8c8c8c',
}

function capKey(caps?: DocumentCaps | null): keyof typeof CAP_COLORS {
  if (!caps) return 'search'
  if (caps.write) return 'write'
  if (caps.read) return 'read'
  if (caps.list) return 'list'
  return 'search'
}

function capLabel(caps?: DocumentCaps | null): string {
  if (!caps) return ''
  if (caps.write) return '可编辑'
  if (caps.read) return '只读'
  if (caps.list) return '可检索 + 看列表'
  return '仅检索'
}

type Column = 'subject' | 'group' | 'kb'

const COLUMN_LABELS: { key: Column; text: string }[] = [
  { key: 'subject', text: '人（成员）' },
  { key: 'group', text: '分组 / 全团队' },
  { key: 'kb', text: '知识库' },
]

const COLUMN_X: Record<Column, number> = {
  subject: PAD + NODE_W / 2,
  group: PAD + NODE_W + COL_GAP + NODE_W / 2,
  kb: PAD + (NODE_W + COL_GAP) * 2 + NODE_W / 2,
}

function columnOf(node: GraphNode): Column {
  if (node.type === 'kb') return 'kb'
  if (node.type === 'group' || node.type === 'team') return 'group'
  return 'subject'
}

interface Placed {
  node: GraphNode
  x: number
  y: number
}

function layout(nodes: GraphNode[]): { placed: Map<string, Placed>; height: number } {
  const groups: Record<Column, GraphNode[]> = { subject: [], group: [], kb: [] }
  for (const node of nodes) {
    groups[columnOf(node)].push(node)
  }
  const tallest = Math.max(groups.subject.length, groups.group.length, groups.kb.length, 1)
  const height = HEAD + PAD * 2 + tallest * NODE_H + (tallest - 1) * NODE_GAP
  const xs: Record<Column, number> = {
    subject: PAD,
    group: PAD + NODE_W + COL_GAP,
    kb: PAD + (NODE_W + COL_GAP) * 2,
  }
  const placed = new Map<string, Placed>()
  for (const column of ['subject', 'group', 'kb'] as Column[]) {
    const list = groups[column]
    if (list.length === 0) continue
    const total = list.length * NODE_H + (list.length - 1) * NODE_GAP
    const startY = HEAD + (height - HEAD - total) / 2
    list.forEach((node, index) => {
      placed.set(node.id, {
        node,
        x: xs[column],
        y: startY + index * (NODE_H + NODE_GAP),
      })
    })
  }
  return { placed, height }
}

function usePaths(edges: GraphEdge[], placed: Map<string, Placed>) {
  return useMemo(() => {
    const items: {
      edge: GraphEdge
      d: string
      color: string
      dashed: boolean
      label: string
      labelWidth: number
      labelX: number
      labelY: number
    }[] = []
    for (const edge of edges) {
      const from = placed.get(edge.source)
      const to = placed.get(edge.target)
      if (!from || !to) continue
      const x1 = from.x + NODE_W
      const y1 = from.y + NODE_H / 2
      const x2 = to.x
      const y2 = to.y + NODE_H / 2
      const dx = Math.max(24, (x2 - x1) / 2)
      const pending = edge.status === 'pending'
      const label = pending ? '待审批' : capLabel(edge.caps)
      items.push({
        edge,
        d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
        color: pending ? CAP_COLORS.pending : CAP_COLORS[capKey(edge.caps)],
        dashed: pending,
        label,
        labelWidth: label.length * 11 + 12,
        labelX: (x1 + x2) / 2,
        labelY: (y1 + y2) / 2,
      })
    }
    // 标签横向位置接近时垂直错开：多条共享边的能力标签不再叠成一团
    items.sort((a, b) => a.labelX - b.labelX)
    for (let index = 1; index < items.length; index += 1) {
      const previous = items[index - 1]
      const current = items[index]
      if (
        Math.abs(current.labelX - previous.labelX) < 70 &&
        Math.abs(current.labelY - previous.labelY) < 14
      ) {
        current.labelY = previous.labelY + 16
      }
    }
    return items
  }, [edges, placed])
}

const NODE_STYLE: Record<
  GraphNode['type'],
  { fill: string; stroke: string; sub: string; badge: string }
> = {
  user: {
    fill: 'var(--ant-color-bg-container)',
    stroke: 'var(--ant-color-border)',
    sub: '成员',
    badge: '人',
  },
  group: {
    fill: 'var(--ant-color-primary-bg)',
    stroke: 'var(--ant-color-primary-border)',
    sub: '分组',
    badge: '组',
  },
  team: {
    fill: 'var(--ant-color-primary-bg)',
    stroke: 'var(--ant-color-primary)',
    sub: '全团队',
    badge: '全员',
  },
  kb: {
    fill: 'var(--ant-color-bg-container)',
    stroke: 'var(--ant-color-border)',
    sub: '知识库',
    badge: '库',
  },
}

export default function ShareGraph({
  graph,
  loading = false,
  onSelectKb,
}: {
  graph: ShareGraphData | null
  loading?: boolean
  onSelectKb?: (kbId: string) => void
}) {
  const shareEdges = useMemo(
    () => (graph?.edges ?? []).filter((edge) => edge.kind === 'share'),
    [graph],
  )
  const { placed, height } = useMemo(() => layout(graph?.nodes ?? []), [graph])
  const paths = usePaths(graph?.edges ?? [], placed)
  const width = NODE_W * 3 + COL_GAP * 2 + PAD * 2
  const showLabels = shareEdges.length <= 6

  if (loading) {
    return (
      <div className="share-graph share-graph--loading">
        <Spin />
      </div>
    )
  }
  if (!graph || graph.nodes.length === 0) {
    return <Empty description="还没有可展示的共享关系" />
  }

  return (
    <div className="share-graph">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        role="img"
        aria-label="知识库共享关系图"
        style={{ maxHeight: 520 }}
      >
        <defs>
          {Object.entries(CAP_COLORS).map(([key, color]) => (
            <marker
              key={key}
              id={`arrow-${key}`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M0 1 L9 5 L0 9 z" fill={color} />
            </marker>
          ))}
        </defs>

        {COLUMN_LABELS.map((column) => (
          <text
            key={column.key}
            x={COLUMN_X[column.key]}
            y={15}
            textAnchor="middle"
            fontSize="11"
            fill="var(--ant-color-text-tertiary)"
          >
            {column.text}
          </text>
        ))}

        {paths.map((item) => {
          const isMember = item.edge.kind === 'member'
          return (
            <g key={item.edge.id}>
              <title>
                {isMember
                  ? `${item.edge.source.replace('user:', '')} 是 ${item.edge.target.replace('group:', '')} 的成员`
                  : `${item.edge.label} · ${item.edge.requested_by_name || ''}`}
              </title>
              <path
                d={item.d}
                fill="none"
                stroke={isMember ? 'var(--ant-color-border)' : item.color}
                strokeWidth={isMember ? 1 : 1.6}
                strokeDasharray={item.dashed ? '4 4' : undefined}
                strokeLinecap="round"
                markerEnd={
                  isMember
                    ? undefined
                    : `url(#arrow-${item.dashed ? 'pending' : capKey(item.edge.caps)})`
                }
                opacity={isMember ? 0.8 : 0.95}
              />
              {showLabels && !isMember ? (
                <>
                  <rect
                    x={item.labelX - item.labelWidth / 2}
                    y={item.labelY - 8}
                    width={item.labelWidth}
                    height={16}
                    rx={8}
                    fill="var(--ant-color-bg-elevated)"
                    stroke={item.color}
                    strokeWidth={1}
                    opacity={0.96}
                  />
                  <text
                    x={item.labelX}
                    y={item.labelY + 3}
                    textAnchor="middle"
                    fontSize="10"
                    fill={item.color}
                  >
                    {item.label}
                  </text>
                </>
              ) : null}
            </g>
          )
        })}

        {[...placed.values()].map(({ node, x, y }) => {
          const style = NODE_STYLE[node.type]
          const names = node.members ?? []
          const withMembers = (node.type === 'group' || node.type === 'team') && names.length > 0
          const visible = names.slice(0, MEMBER_LIMIT)
          const extra = names.length - visible.length
          const memberText = `${visible.join('、')}${extra > 0 ? ` +${extra}` : ''}`
          const shortMemberText =
            memberText.length > 20 ? `${memberText.slice(0, 19)}…` : memberText
          const sub =
            node.type === 'kb'
              ? `${node.document_count ?? 0} 篇 · ${node.owner_name || '未知库主'}`
              : node.type === 'group'
                ? `${node.member_count ?? 0} 人`
                : node.type === 'team'
                  ? `${node.member_count ?? 0} 人可见`
                  : node.is_me
                    ? '我'
                    : style.sub
          const graphNode = (
            <g
              key={node.id}
              transform={`translate(${x}, ${y})`}
              className={
                node.type === 'kb' && onSelectKb ? 'share-graph__node--clickable' : undefined
              }
              onClick={
                node.type === 'kb' && onSelectKb
                  ? () => onSelectKb(node.id.replace('kb:', ''))
                  : undefined
              }
            >
              {withMembers ? null : (
                <title>{`${node.label}${node.type === 'kb' ? `（${node.document_count ?? 0} 篇文档）` : ''}`}</title>
              )}
              <rect
                width={NODE_W}
                height={NODE_H}
                rx={10}
                fill={style.fill}
                stroke={node.is_me ? 'var(--ant-color-primary)' : style.stroke}
                strokeWidth={node.is_me ? 1.6 : 1}
              />
              <rect width={4} height={NODE_H} rx={2} fill={style.stroke} opacity={0.9} />
              <text
                x={14}
                y={withMembers ? 19 : 25}
                fontSize="13"
                fill="var(--ant-color-text)"
                fontWeight={500}
              >
                {node.label.length > 12 ? `${node.label.slice(0, 11)}…` : node.label}
              </text>
              <text
                x={14}
                y={withMembers ? 34 : 42}
                fontSize="11"
                fill="var(--ant-color-text-tertiary)"
              >
                {sub}
              </text>
              {withMembers ? (
                <text x={14} y={50} fontSize="10" fill="var(--ant-color-text-tertiary)">
                  {shortMemberText}
                </text>
              ) : null}
            </g>
          )
          if (!withMembers) return graphNode
          const hiddenCount = (node.member_count ?? 0) - names.length
          return (
            <Tooltip
              key={node.id}
              title={
                <div className="share-graph__tip">
                  <strong>{node.label}</strong>
                  <div>
                    成员（{names.length}）：{names.join('、')}
                  </div>
                  {hiddenCount > 0 ? (
                    <div className="share-graph__tip-note">
                      另有 {hiddenCount} 人（当前视角不可见）
                    </div>
                  ) : null}
                </div>
              }
            >
              {graphNode}
            </Tooltip>
          )
        })}
      </svg>

      <div className="share-graph__legend">
        <span className="share-graph__legend-item">
          <i style={{ background: CAP_COLORS.search }} />
          仅检索
        </span>
        <span className="share-graph__legend-item">
          <i style={{ background: CAP_COLORS.list }} />
          可检索 + 看列表
        </span>
        <span className="share-graph__legend-item">
          <i style={{ background: CAP_COLORS.read }} />
          只读
        </span>
        <span className="share-graph__legend-item">
          <i style={{ background: CAP_COLORS.write }} />
          可编辑
        </span>
        <span className="share-graph__legend-item">
          <i className="is-dashed" />
          待审批
        </span>
      </div>
    </div>
  )
}
