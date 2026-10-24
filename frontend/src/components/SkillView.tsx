import { ApiOutlined, FolderOpenOutlined } from '@ant-design/icons'
import { Alert, Empty, Skeleton, Space, Tag, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'

import { ApiError, listSkillResources } from '../services/api'
import type { SkillInfo, SkillResourceInfo } from '../types/api'
import { formatDateTime } from '../utils/format'
import ViewHeader from './ViewHeader'
import { useViewStack } from './ViewStack'

const { Text, Paragraph } = Typography

const RESOURCE_GROUPS = [
  { key: 'references', label: 'references/', hint: '参考文档、长资料' },
  { key: 'resources', label: 'resources/', hint: '模板、静态资源' },
  { key: 'scripts', label: 'scripts/', hint: '脚本只保存，永不执行' },
] as const

type ResourceGroupKey = (typeof RESOURCE_GROUPS)[number]['key'] | 'root'

function groupOf(resource: SkillResourceInfo): ResourceGroupKey {
  const first = resource.name.split('/')[0]
  if (first === 'references' || first === 'resources' || first === 'scripts') return first
  return 'root'
}

/** 技能只读详情视图：把 L1 目录 / L2 正文 / L3 附件三段实际展示出来。 */
export default function SkillView({ skill }: { skill: SkillInfo }) {
  const { back } = useViewStack()
  const [resources, setResources] = useState<SkillResourceInfo[]>([])
  const [resourcesLoading, setResourcesLoading] = useState(true)
  const [resourcesError, setResourcesError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setResourcesLoading(true)
    setResourcesError(null)
    listSkillResources(skill.skill_id)
      .then((data) => {
        if (!cancelled) setResources(data.resources)
      })
      .catch((err) => {
        if (!cancelled) {
          setResourcesError(err instanceof ApiError ? err.message : '加载技能附件失败')
        }
      })
      .finally(() => {
        if (!cancelled) setResourcesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [skill.skill_id])

  const grouped = useMemo(() => {
    const groups: Record<ResourceGroupKey, SkillResourceInfo[]> = {
      references: [],
      resources: [],
      scripts: [],
      root: [],
    }
    for (const resource of resources) {
      groups[groupOf(resource)].push(resource)
    }
    return groups
  }, [resources])

  const hasScripts = grouped.scripts.length > 0

  return (
    <div className="view-panel">
      <ViewHeader
        title={
          <>
            <ApiOutlined className="view-header__icon" /> {skill.name}
          </>
        }
        subtitle="技能详情"
        onBack={back}
        extra={
          <Space size={8}>
            <Tag>{skill.builtin ? '内置' : '自定义'}</Tag>
            <Tag color={skill.enabled ? 'green' : 'default'}>
              {skill.enabled ? '已启用' : '已停用'}
            </Tag>
          </Space>
        }
      />
      <div className="view-body">
        <div className="skill-view">
          <section className="skill-view__section">
            <Space size={8} wrap>
              <Tag color="blue">L1 目录</Tag>
              <Text type="secondary">
                Planner 只看到 skill_id / 名称 / 适用场景，不读取正文与附件
              </Text>
            </Space>
            <div className="skill-stage-card">
              <Text type="secondary">skill_id</Text>
              <Text code>{skill.skill_id}</Text>
              <Text type="secondary">名称</Text>
              <Text strong>{skill.name}</Text>
              <Text type="secondary">适用场景（Planner 判断是否调用）</Text>
              <p className="skill-view__desc">{skill.description}</p>
            </div>
          </section>

          <section className="skill-view__section">
            <Space size={8} wrap>
              <Tag color="purple">L2 指令正文</Tag>
              <Text type="secondary">命中技能后作为 system 指令注入，只注入一次</Text>
            </Space>
            <pre className="doc-view__text">{skill.content}</pre>
          </section>

          <section className="skill-view__section">
            <Space size={8} wrap>
              <Tag color="gold">L3 按需附件</Tag>
              <Text type="secondary">
                目录只暴露路径；模型显式请求时才注入正文，最多追加一次调用
              </Text>
            </Space>

            {resourcesError ? (
              <Alert type="error" showIcon message={resourcesError} />
            ) : resourcesLoading ? (
              <Skeleton active paragraph={{ rows: 2 }} />
            ) : resources.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="没有附件，技能只使用 L2 正文"
              />
            ) : (
              <>
                {hasScripts ? (
                  <Alert
                    type="warning"
                    showIcon
                    message="scripts/ 下的文件只保存，系统永远不会执行"
                  />
                ) : null}
                {RESOURCE_GROUPS.filter(
                  (group) => group.key !== 'scripts' || grouped.scripts.length > 0,
                ).map((group) =>
                  grouped[group.key].length === 0 ? null : (
                    <div key={group.key} className="skill-resource-group">
                      <Space size={8} wrap>
                        <FolderOpenOutlined />
                        <Text strong>{group.label}</Text>
                        <Text type="secondary">
                          {group.hint}（{grouped[group.key].length}）
                        </Text>
                      </Space>
                      {grouped[group.key].map((resource) => (
                        <div key={resource.resource_id} className="skill-resource-item">
                          <Text code>{resource.name}</Text>
                          <Paragraph
                            type="secondary"
                            ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
                            className="skill-resource-item__content"
                          >
                            {resource.content}
                          </Paragraph>
                        </div>
                      ))}
                    </div>
                  ),
                )}
                {grouped.root.length > 0 ? (
                  <div className="skill-resource-group">
                    <Space size={8} wrap>
                      <FolderOpenOutlined />
                      <Text strong>根目录</Text>
                      <Text type="secondary">兼容旧技能包的 reference.md</Text>
                    </Space>
                    {grouped.root.map((resource) => (
                      <div key={resource.resource_id} className="skill-resource-item">
                        <Text code>{resource.name}</Text>
                        <Paragraph
                          type="secondary"
                          ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
                          className="skill-resource-item__content"
                        >
                          {resource.content}
                        </Paragraph>
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            )}
          </section>

          <section className="skill-view__section">
            <Space size={8} wrap>
              <Tag>文件存储</Tag>
              <Text type="secondary">文件是唯一内容源；启用状态写在 sidecar，不改写 SKILL.md</Text>
            </Space>
            <pre className="skill-file-tree">{`data/skills/${skill.skill_id}/
├── SKILL.md            # YAML frontmatter + 指令正文
├── .skill-state.json   # enabled / builtin / 来源 / 时间戳
├── references/         ${grouped.references.length} 个附件
├── resources/          ${grouped.resources.length} 个附件
└── scripts/            ${grouped.scripts.length} 个脚本（不执行）`}</pre>
          </section>

          {skill.source_filename ? (
            <section className="skill-view__section">
              <Text type="secondary">来源</Text>
              <Text>{skill.source_filename}</Text>
            </section>
          ) : null}

          <Text type="secondary" className="skill-view__meta">
            更新于 {formatDateTime(skill.updated_at)}
          </Text>
        </div>
      </div>
    </div>
  )
}
