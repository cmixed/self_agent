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

- ``DEFAULT_TOTAL_CHARS``：用户可理解的**目标总字数**（软目标，写进提示词）；
- ``MAX_TOTAL_CHARS`` / ``MIN_TOTAL_CHARS``：配置夹取范围。

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

# --- 重新规划（replan）---
# replan 会重置计划、大纲与全部章节，代价远高于章级重写；每单最多 1 次。
MAX_REPLANS = 1
