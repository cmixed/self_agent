"""从文档生成技能草稿（LLM 侧）。

职责边界（AGENTS.md §4）：

- 这里只负责「提示词 + 结构化 Schema + 一次有限重试的模型调用」；
- 取文档原文、截断、去重检查等编排逻辑在 ``services/skill_generation_service.py``；
- 生成结果**不落库**：由前端确认/编辑后走既有 ``POST /api/skills``。

技能是「怎么做的指令」，不是「资料讲了什么」。因此提示词强制模型只提炼
文档中真实存在的方法/步骤/判断标准，禁止补写文档之外的领域知识。
"""

from __future__ import annotations

from pydantic import BaseModel

from app.llm.base import ChatMessage, LLMProvider

# 生成失败后的额外尝试次数（与 Planner 同级的有限重试，§10/§27）
MAX_GENERATION_RETRIES = 1

_SYSTEM_PROMPT = """你是一个「技能设计师」。用户会给你一份参考资料（可能是 Markdown、\
笔记或论文片段），你要把资料里**可复用的做法**提炼成一个 Agent 技能。

技能是 Agent 执行某类任务时的 system 指令，因此它必须描述「怎么做」，\
而不是「资料讲了什么」。

硬性要求：
1. 只提炼资料中明确出现的方法、步骤、检查项、判断标准。不得补充资料之外的\
   领域知识，不得编造数据、指标、结论或引用。
2. 资料若只是概念介绍、缺少可执行流程，就围绕「如何用这份资料的框架去分析\
   问题」设计指令，并在适用场景里限定范围。
3. 用第二人称祈使句（「你是……」）直接写给 Agent 看，不要出现「本文档」\
   「作者认为」这类转述口吻。
4. 输出必须是可执行指令，包含：角色定位、执行步骤（3-6 步）、输出格式要求、\
   禁止事项（至少包含「资料中不存在的信息不得编造」）。

字段要求：
- name：不超过 20 字的中文短语，体现技能用途，不要带书名号或引号。
- description：不超过 80 字，必须写成「当……时使用」的触发条件，供 Planner \
  判断是否调用。
- content：150-600 字，纯文本（可用 1) 2) 3) 分点）。

只输出 JSON，不要输出解释文字或 Markdown 代码块，结构为：
{"name": "...", "description": "...", "content": "..."}
"""


class SkillDraftModel(BaseModel):
    """模型返回的技能草稿（字段缺失会触发一次重试）。"""

    name: str
    description: str
    content: str


def build_messages(*, text: str, hint: str = "") -> list[ChatMessage]:
    """构造生成请求；``text`` 已由服务层截断。"""
    instruction = "请根据下面的资料设计一个技能。"
    if hint.strip():
        instruction += f"\n额外要求：{hint.strip()}"
    user = f"{instruction}\n\n<资料>\n{text}\n</资料>"
    return [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user", content=user),
    ]


async def generate_skill_draft(
    llm: LLMProvider,
    *,
    text: str,
    hint: str = "",
    max_retries: int = MAX_GENERATION_RETRIES,
) -> SkillDraftModel:
    """调用模型生成技能草稿；JSON/Schema 解析失败时有限重试。"""
    return await llm.chat_structured(
        build_messages(text=text, hint=hint),
        SkillDraftModel,
        temperature=0.2,
        max_retries=max_retries,
    )
