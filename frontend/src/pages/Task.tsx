import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  Result,
  Row,
  Space,
  Statistic,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useEffect, useRef } from 'react'

import AgentProgress from '../components/AgentProgress'
import type { MacroStage } from '../components/AgentProgress'
import EmptyState from '../components/EmptyState'
import PageContainer from '../components/PageContainer'
import MarkdownView from '../components/MarkdownView'
import { SAMPLE_TASKS, useTaskRun } from '../state/taskRun'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const PAGE_TITLE = '任务'
const PAGE_DESCRIPTION = '提交一个复杂任务：Agent 会先规划、再检索你的资料、分章节撰写并自我校验。'
const PAGE_MAX_WIDTH = 1080

const TARGET_LABEL = (target: string) =>
  target === 'document' ? '整篇文档' : `章节 ${target.replace('chapter_', '')}`

export default function TaskPage() {
  const {
    query,
    setQuery,
    running,
    hasStarted,
    aborted,
    error,
    dismissError,
    taskId,
    elapsed,
    duration,
    round,
    log,
    nodes,
    plannerNotes,
    chapterNotes,
    chapterList,
    writtenChapters,
    retrievalSkipped,
    plan,
    outline,
    sources,
    validation,
    finalAnswer,
    retrievedCount,
    replans,
    failedCount,
    passedCount,
    activeTab,
    setActiveTab,
    copied,
    run,
    abort,
    clear,
    copy,
    download,
  } = useTaskRun()

  const resultRef = useRef<HTMLDivElement | null>(null)

  // 结果出现后定位（含从其它页面切回来的情况）
  useEffect(() => {
    if (finalAnswer !== null) {
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [finalAnswer])

  const chapterStageStatus = (): MacroStage['status'] => {
    if (nodes.writer === 'error' || nodes.validator === 'error') return 'error'
    if (nodes.writer === 'process' || nodes.validator === 'process') return 'process'
    if (nodes.writer === 'finish' && nodes.validator === 'finish') return 'finish'
    return 'wait'
  }

  const macroStages: MacroStage[] = [
    {
      key: 'planner',
      title: '分析任务并生成计划',
      status: nodes.planner as MacroStage['status'],
      badge: replans > 0 ? <Tag color="volcano">重新规划 {replans} 次</Tag> : undefined,
      notes: plannerNotes,
    },
    {
      key: 'researcher',
      title: '检索个人知识库',
      status: nodes.researcher as MacroStage['status'],
      skipped: retrievalSkipped,
      badge:
        retrievedCount !== null ? (
          <Tag color={retrievedCount > 0 ? 'blue' : 'orange'}>{retrievedCount} 条片段</Tag>
        ) : undefined,
    },
    {
      key: 'outline',
      title: '生成文章大纲',
      status: nodes.outline as MacroStage['status'],
      badge: outline.length > 0 ? <Tag>{outline.length} 章</Tag> : undefined,
    },
    {
      key: 'chapters',
      title: '逐章撰写与校验',
      status: chapterStageStatus(),
      note: outline.length > 0 ? `已写 ${writtenChapters}/${outline.length} 章` : undefined,
      progress: outline.length > 0 ? { done: writtenChapters, total: outline.length } : undefined,
      chapters: chapterList,
      // 只展示仍未解决的提示；已修正的章节提示会消失（历史见「执行日志」）
      notes: chapterList
        .filter((chapter) => chapter.validation !== 'passed')
        .flatMap((chapter) => chapterNotes[chapter.index] ?? []),
    },
    {
      key: 'summarizer',
      title: '整合最终结果',
      status: nodes.summarizer as MacroStage['status'],
      badge: finalAnswer !== null ? <Tag color="green">已整合</Tag> : undefined,
    },
  ]

  const handleSend = () => {
    void run()
  }

  return (
    <PageContainer
      title={PAGE_TITLE}
      description={PAGE_DESCRIPTION}
      maxWidth={PAGE_MAX_WIDTH}
      extra={running ? <Tag color="processing">运行中</Tag> : null}
    >
      <Card title="提交任务">
        <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
          <TextArea
            id="task-query"
            name="query"
            autoSize={{ minRows: 3, maxRows: 8 }}
            value={query}
            disabled={running}
            placeholder="例如：根据我的资料写一篇 RAG 技术综述"
            onChange={(event) => setQuery(event.target.value)}
            onPressEnter={(event) => {
              // Enter 直接运行任务；Shift+Enter 换行
              if (!event.shiftKey && !running) {
                event.preventDefault()
                handleSend()
              }
            }}
          />
          <div className="composer-actions">
            <Space size={[8, 8]} wrap>
              <Text type="secondary">示例：</Text>
              {SAMPLE_TASKS.map((sample) => (
                <Tag
                  key={sample}
                  className="sample-tag"
                  onClick={() => {
                    if (!running) setQuery(sample)
                  }}
                >
                  {sample}
                </Tag>
              ))}
            </Space>
            <Space>
              {running ? (
                <Button danger onClick={abort}>
                  终止任务
                </Button>
              ) : (
                <Button type="primary" onClick={handleSend}>
                  运行任务
                </Button>
              )}
              <Button
                disabled={running}
                onClick={() => {
                  setQuery('')
                  clear()
                }}
              >
                清空
              </Button>
            </Space>
          </div>
          <Text type="secondary" className="composer-hint">
            Enter 运行任务 · Shift + Enter 换行；运行中可随时终止，切换到其它页面任务会继续执行
          </Text>
        </Space>
      </Card>

      <Card title="执行进度">
        <AgentProgress
          stages={macroStages}
          elapsedSeconds={elapsed}
          running={running}
          hasStarted={hasStarted}
          round={round}
          log={log}
        />
      </Card>

      {aborted && (
        <Alert
          type="warning"
          showIcon
          title="任务已终止"
          description="已关闭与后端的连接，Agent 会同步取消，不会继续消耗模型调用。已生成的计划 / 大纲 / 章节进度保留在上方。正文只在任务正常完成时返回，因此终止后无法查看已写章节的正文。"
        />
      )}

      {error && (
        <Result
          status="error"
          title="任务未能完成"
          subTitle={error}
          extra={
            <>
              <Button type="primary" onClick={handleSend} disabled={running}>
                重试
              </Button>
              <Button onClick={dismissError}>关闭</Button>
            </>
          }
        />
      )}

      {finalAnswer !== null && (
        <div ref={resultRef}>
          <Card
            title="执行结果"
            extra={
              <Space>
                <Tooltip title="复制 Markdown 原文">
                  <Button size="small" onClick={() => void copy()}>
                    {copied ? '已复制' : '复制'}
                  </Button>
                </Tooltip>
                <Button size="small" onClick={download}>
                  下载 .md
                </Button>
              </Space>
            }
          >
            <Tabs
              activeKey={activeTab}
              onChange={setActiveTab}
              items={[
                {
                  key: 'overview',
                  label: '概览',
                  children: (
                    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
                      <Row gutter={[16, 16]}>
                        <Col xs={12} lg={6}>
                          <Statistic title="章节数" value={outline.length} />
                        </Col>
                        <Col xs={12} lg={6}>
                          <Statistic title="命中片段" value={retrievedCount ?? 0} />
                        </Col>
                        <Col xs={12} lg={6}>
                          <Statistic title="重新规划" value={replans} suffix="次" />
                        </Col>
                        <Col xs={12} lg={6}>
                          <Statistic title="执行耗时" value={duration ?? elapsed} suffix="秒" />
                        </Col>
                      </Row>

                      {failedCount > 0 && (
                        <Alert
                          type="warning"
                          showIcon
                          title={`有 ${failedCount} 个章节已达重试上限、未通过校验`}
                          description="这些章节在正文中以「未通过校验」标注，其余章节正常产出。"
                        />
                      )}

                      {validation && (
                        <Descriptions column={1} size="small" bordered>
                          <Descriptions.Item label="校验对象">
                            {TARGET_LABEL(validation.target)}
                          </Descriptions.Item>
                          <Descriptions.Item label="校验结论">
                            <Tag color={validation.passed ? 'green' : 'red'}>
                              {validation.passed ? '通过' : '未通过'}
                            </Tag>
                          </Descriptions.Item>
                          <Descriptions.Item label="章节情况">
                            共 {outline.length} 章：通过 {passedCount} 章
                            {failedCount > 0 ? `，未通过 ${failedCount} 章` : ''}
                          </Descriptions.Item>
                          {taskId && (
                            <Descriptions.Item label="任务 ID">
                              <Text code copyable>
                                {taskId}
                              </Text>
                            </Descriptions.Item>
                          )}
                        </Descriptions>
                      )}
                    </Space>
                  ),
                },
                {
                  key: 'content',
                  label: '正文',
                  children: finalAnswer ? (
                    <MarkdownView content={finalAnswer} />
                  ) : (
                    <Text type="secondary">尚未生成正文</Text>
                  ),
                },
                {
                  key: 'chapters',
                  label: '章节',
                  children:
                    chapterList.length > 0 ? (
                      <ol className="plain-list">
                        {chapterList.map((chapter) => (
                          <li key={chapter.index}>
                            <Tag
                              color={
                                chapter.validation === 'passed'
                                  ? 'green'
                                  : chapter.validation === 'failed'
                                    ? 'red'
                                    : chapter.written > 0
                                      ? 'blue'
                                      : 'default'
                              }
                            >
                              {chapter.validation === 'passed'
                                ? '通过'
                                : chapter.validation === 'failed'
                                  ? '未通过'
                                  : chapter.written > 0
                                    ? `已写 ×${chapter.written}`
                                    : '待写'}
                            </Tag>
                            {chapter.title}
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <EmptyState compact title="尚未生成大纲" />
                    ),
                },
                {
                  key: 'plan',
                  label: '计划',
                  children: plan ? (
                    <Space orientation="vertical" size="small" style={{ width: '100%' }}>
                      <Paragraph style={{ marginBottom: 0 }}>
                        <Text strong>目标：</Text>
                        {plan.goal}
                      </Paragraph>
                      <Paragraph style={{ marginBottom: 0 }}>
                        <Text strong>需要知识库检索：</Text>
                        <Tag color={plan.needs_retrieval ? 'blue' : 'default'}>
                          {plan.needs_retrieval ? '需要' : '不需要'}
                        </Tag>
                      </Paragraph>
                      <ol className="plain-list">
                        {plan.steps.map((step) => (
                          <li key={step.id}>
                            <Tag>{step.type}</Tag>
                            {step.description}
                          </li>
                        ))}
                      </ol>
                    </Space>
                  ) : (
                    <EmptyState compact title="尚未生成计划" />
                  ),
                },
                {
                  key: 'validation',
                  label: '校验',
                  children: validation ? (
                    <Space orientation="vertical" size="small" style={{ width: '100%' }}>
                      <div>
                        <Text strong>结论：</Text>
                        <Tag color={validation.passed ? 'green' : 'red'}>
                          {validation.passed ? '通过' : '未通过'}
                        </Tag>
                        <Text type="secondary">（{TARGET_LABEL(validation.target)}）</Text>
                      </div>
                      {validation.issues.length > 0 ? (
                        <ul className="plain-list">
                          {validation.issues.map((issue, index) => (
                            <li key={index}>
                              <Text type="warning">{issue}</Text>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <Text type="secondary">没有发现问题</Text>
                      )}
                    </Space>
                  ) : (
                    <EmptyState compact title="尚未执行校验" />
                  ),
                },
                {
                  key: 'sources',
                  label: `来源${sources.length > 0 ? `（${sources.length}）` : ''}`,
                  children:
                    sources.length > 0 ? (
                      <ol className="plain-list">
                        {sources.map((source) => (
                          <li key={source.chunk_id}>
                            <Text>
                              [{source.index}] {source.filename}
                              {source.page ? `（第 ${source.page} 页）` : ''}
                            </Text>
                            {typeof source.score === 'number' && (
                              <Tag style={{ marginLeft: 8 }}>
                                相似度 {source.score.toFixed(3)}
                              </Tag>
                            )}
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <EmptyState
                        compact
                        title="本次任务未使用知识库来源"
                        hint="计划不需要检索，或知识库为空"
                      />
                    ),
                },
              ]}
            />
          </Card>
        </div>
      )}
    </PageContainer>
  )
}
