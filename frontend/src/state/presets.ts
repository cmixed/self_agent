/**
 * 工作台预设任务（静态 UI 输入快捷方式，与 PIPELINE_STEPS 同类的界面文案；
 * 展示类数据一律来自真实后端，两者界限不得混淆）。
 */

export interface PresetTask {
  id: string
  title: string
  description: string
  query: string
}

export const PRESET_TASKS: PresetTask[] = [
  {
    id: 'rag-survey',
    title: 'RAG 技术综述',
    description: '基于知识库资料撰写一篇带引用来源的技术综述',
    query: '根据我的资料写一篇 RAG 技术综述',
  },
  {
    id: 'compare-report',
    title: '技术方案对比报告',
    description: '调研资料中的技术方案，输出对比与选型建议',
    query: '调研我资料里的几种技术方案，输出对比报告并给出选型建议',
  },
  {
    id: 'study-notes',
    title: '学习笔记',
    description: '整理资料，生成一份带目录与来源引用的学习笔记',
    query: '整理我的资料，生成一份带目录与来源引用的学习笔记',
  },
  {
    id: 'paper-review',
    title: '论文精读报告',
    description: '逐篇总结资料中论文的核心贡献、方法与局限',
    query: '总结我资料里的论文，逐篇输出核心贡献、方法与局限',
  },
]
