"""跨层共用的数值上限。

放在这里而不是某个节点模块：``app.core.config``（校验/夹取用户配置）与
``app.agents.chapters``（循环边界）都需要，而 config 直接 import agents 会
经 ``app.models.state`` → ``app.llm`` → ``app.llm.factory`` → ``app.core.config``
形成循环导入。本模块**不依赖任何项目模块**，可被任意层安全引用。

三类语义必须区分（见 AGENTS.md §27 禁止无限循环）：

- ``HARD_SECTION_CEILING``：安全兜底，只防异常，不参与产品决策；
- ``DEFAULT_MAX_SECTIONS``：单次任务的生成上限（可配置，夹在 [MIN, CEILING]）；
- ``DEFAULT_TARGET_SECTIONS``：提示词里的**参考上限**（可配置，≤ 生成上限）；
- ``SCHEMA_SECTION_GUARD``：模型输出结构的防爆上限，远高于生成上限——
  超出生成上限时**截断并说明**，而不是让整单任务失败。

章节数由任务实际需要决定：简单内容可以只有 1 章（整篇不拆分），
因此 ``MIN_SECTIONS`` 只作为「至少有一章正文」的结构下限，不再强制 3 章。

篇幅（字数）同样分两件事：

- ``DEFAULT_TOTAL_CHARS``：用户可理解的**请求总字数**（软目标，写进提示词）；
- ``MAX_TOTAL_CHARS`` / ``MIN_TOTAL_CHARS``：配置夹取范围。

实际写作时还要再区分「请求目标」与「资料可支撑目标」：资料不足时按
``SOURCE_LIMITED_RATIO`` / ``SOURCE_EXPANSION_FACTOR`` 下调参考篇幅，
宁可短而扎实，不硬凑（见 ``app.agents.budget``）。

**不设**「每章 max_tokens 硬上限」：tokens 是实现细节，且截断会让流程拿到
半截章节；真正需要的是把截断暴露出来（见 ``LLMResponse.finish_reason``）。
"""

from __future__ import annotations

# --- 篇幅（目标总字数，软目标）---
MIN_TOTAL_CHARS = 1500
DEFAULT_TOTAL_CHARS = 6000
MAX_TOTAL_CHARS = 40000

# --- 章节数 ---
MIN_SECTIONS = 1
DEFAULT_TARGET_SECTIONS = 6
DEFAULT_MAX_SECTIONS = 12
HARD_SECTION_CEILING = 20
SCHEMA_SECTION_GUARD = 50

# --- 技能执行输出（分析结论，不是最终长文）---
# 技能结论是 Writer 的上下文，不是越多越好：软目标控制篇幅，硬上限只做安全兜底。
SKILL_TARGET_MIN_CHARS = 800
SKILL_TARGET_MAX_CHARS = 3000
SKILL_HARD_MAX_CHARS = 5000
# 拼进 outline / writer 的技能结论总预算；超出时显式节选，避免上下文膨胀。
MAX_SKILL_CONTEXT_CHARS = 4000

# --- 从长文档生成技能 ---
# 每段最多送入模型的字符数（可被 SKILL_GENERATE_MAX_CHARS 调整）；
# 长文档分块提炼，但块数有上限，避免一次生成无限次调用。
MAX_SKILL_GENERATION_CHUNKS = 6
MAX_SKILL_EXTRACTION_CHARS = 12000
MAX_SKILL_INSTRUCTION_CHARS = 600

# --- 长文篇幅与章节建议 ---
# 章节预算参考值：只用于估算建议章节数，不是单章硬指标。
LONGFORM_SECTION_BUDGET_CHARS = 1800
# 兼容旧名（此前语义是“每章约 2000 字”）；新代码请使用上面的名字。
LONGFORM_CHAPTER_TARGET_CHARS = LONGFORM_SECTION_BUDGET_CHARS
# 单章参考区间的浮动范围：软目标，允许资料不足时写短。
CHAPTER_LENGTH_LOW_FACTOR = 0.6
CHAPTER_LENGTH_HIGH_FACTOR = 1.5
# 最终篇幅审计的容忍区间：超出不自动改写，只在步骤摘要/日志中如实提示。
LONGFORM_LENGTH_LOW_FACTOR = 0.6
LONGFORM_LENGTH_HIGH_FACTOR = 1.5

# --- 资料量自适应写作预算 ---
# 检索资料少于请求目标的一半时，认为资料受限，按资料量下调参考篇幅。
SOURCE_LIMITED_RATIO = 0.5
# 资料可以支撑约两倍篇幅的分析/串联/解释；不是硬截断。
SOURCE_EXPANSION_FACTOR = 2.0
# 资料极少时的最低参考篇幅：写一段简短、诚实的说明，而不是硬凑长文。
MIN_GROUNDED_TOTAL_CHARS = 300
# 资料受限时技能结论允许更短（技能结论是写作依据，不是最终文章）。
SKILL_TARGET_MIN_CHARS_SOURCE_LIMITED = 300

# --- 重新规划（replan）---
# replan 会重置计划、大纲与全部章节，代价远高于章级重写；每单最多 1 次。
MAX_REPLANS = 1
