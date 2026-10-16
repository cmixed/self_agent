import { ApiOutlined } from '@ant-design/icons'
import { Space, Tag, Typography } from 'antd'

import type { SkillInfo } from '../types/api'
import { formatDateTime } from '../utils/format'
import ViewHeader from './ViewHeader'
import { useViewStack } from './ViewStack'

const { Text } = Typography

/** 技能只读详情视图：与「文档阅读」同一形态（内容区独立视图 + 统一返回）。 */
export default function SkillView({ skill }: { skill: SkillInfo }) {
  const { back } = useViewStack()

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
            <Text type="secondary">适用场景</Text>
            <p className="skill-view__desc">{skill.description}</p>
          </section>

          <section className="skill-view__section">
            <Text type="secondary">技能指令</Text>
            <pre className="doc-view__text">{skill.content}</pre>
          </section>

          <Text type="secondary" className="skill-view__meta">
            更新于 {formatDateTime(skill.updated_at)}
          </Text>
        </div>
      </div>
    </div>
  )
}
