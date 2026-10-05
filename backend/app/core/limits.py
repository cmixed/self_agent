"""跨层共用的数值上限。

放在这里而不是某个节点模块：``app.core.config``（校验/夹取用户配置）与
``app.agents.chapters``（循环边界）都需要，而 config 直接 import agents 会
经 ``app.models.state`` → ``app.llm`` → ``app.llm.factory`` → ``app.core.config``
形成循环导入。本模块**不依赖任何项目模块**，可被任意层安全引用。

三类语义必须区分（见 AGENTS.md §27 禁止无限循环）：

- ``HARD_SECTION_CEILING``：安全兜底，只防异常，不参与产品决策；
- ``DEFAULT_MAX_SECTIONS``：单次任务的生成上限（可配置，夹在 [MIN, CEILING]）；
- ``DEFAULT_TARGET_SECTIONS``：提示词里的目标篇幅（可配置，≤ 生成上限）；
- ``SCHEMA_SECTION_GUARD``：模型输出结构的防爆上限，远高于生成上限——
  超出生成上限时**截断并说明**，而不是让整单任务失败。
"""

from __future__ import annotations

# --- 章节数 ---
MIN_SECTIONS = 3
DEFAULT_TARGET_SECTIONS = 6
DEFAULT_MAX_SECTIONS = 12
HARD_SECTION_CEILING = 20
SCHEMA_SECTION_GUARD = 50
