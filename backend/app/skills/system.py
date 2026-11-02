"""系统级技能常量。

系统技能不是用户可编辑的指令模块，而是 Agent 的一项确定性能力：
Planner 仍然通过 ``type="skill"`` 选择它，但 Skills 节点会走专用分支，
直接读取知识库原文件全文，不调用模型生成正文。

当前只有一种系统技能：``output_mode=verbatim``。
"""

from __future__ import annotations

SYSTEM_VERBATIM_SKILL_ID = "system-verbatim"
SYSTEM_VERBATIM_SKILL_NAME = "知识库原文输出"
SYSTEM_VERBATIM_SKILL_DESCRIPTION = (
    "当任务要求完整、逐字引用或原样输出知识库中某篇文档时使用。"
    "系统会直接读取原文件并插入全文，不经过模型改写；"
    "不要用它来总结、改写或仅引用片段。"
)
# 系统技能正文只在被误当作普通技能时使用；正常路径不会把这段文字送给模型。
SYSTEM_VERBATIM_SKILL_CONTENT = (
    "这是系统保留技能。任务需要知识库原文时，系统会直接读取原文件并插入全文；不要在这里生成内容。"
)


def system_verbatim_entry() -> dict[str, object]:
    """构造系统技能目录条目（由 API 层追加到 Agent 技能快照）。"""
    return {
        "skill_id": SYSTEM_VERBATIM_SKILL_ID,
        "name": SYSTEM_VERBATIM_SKILL_NAME,
        "description": SYSTEM_VERBATIM_SKILL_DESCRIPTION,
        "content": SYSTEM_VERBATIM_SKILL_CONTENT,
        "output_mode": "verbatim",
        "verbatim_scope": "knowledge_base",
    }


def is_verbatim_skill(skill_id: str | None, *, output_mode: str | None = None) -> bool:
    """判断一个技能是否为原文输出系统技能。"""
    return output_mode == "verbatim" or skill_id == SYSTEM_VERBATIM_SKILL_ID
