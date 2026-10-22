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
from app.prompts import render_prompt

# 生成失败后的额外尝试次数（与 Planner 同级的有限重试，§10/§27）
MAX_GENERATION_RETRIES = 1

_SYSTEM_PROMPT = render_prompt("skill_generate.md")


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
