"""从文档生成技能草稿（LLM 侧）。

职责边界（AGENTS.md §4）：

- 这里只负责「提示词 + 结构化 Schema + 一次有限重试的模型调用」；
- 取文档原文、截断、去重检查等编排逻辑在 ``services/skill_generation_service.py``；
- 生成结果**不落库**：由前端确认/编辑后走既有 ``POST /api/skills``。

技能是「怎么做的指令」，不是「资料讲了什么」。因此提示词强制模型只提炼
文档中真实存在的方法/步骤/判断标准，禁止补写文档之外的领域知识。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

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


class ChunkMethodModel(BaseModel):
    """单个资料片段中提炼出的做法（长文档分块提炼使用）。"""

    name: str = Field(min_length=1, max_length=80)
    when: str = Field(default="", max_length=200)
    steps: list[str] = Field(default_factory=list, max_length=8)
    checks: list[str] = Field(default_factory=list, max_length=6)


class ChunkExtractionModel(BaseModel):
    """一段资料的可复用做法清单；允许为空（概念型资料）。"""

    methods: list[ChunkMethodModel] = Field(default_factory=list, max_length=8)


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


def build_chunk_messages(*, text: str, chunk_index: int, chunk_total: int) -> list[ChatMessage]:
    """构造单段资料的提炼请求；资料放在 user，避免与 system 指令混在一起。"""
    return [
        ChatMessage(
            role="system",
            content=render_prompt(
                "skill_extract_chunk.md",
                chunk_index=chunk_index,
                chunk_total=chunk_total,
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"请提炼第 {chunk_index}/{chunk_total} 段资料中的可复用做法。\n\n"
                f"<资料>\n{text}\n</资料>"
            ),
        ),
    ]


async def extract_chunk_methods(
    llm: LLMProvider,
    *,
    text: str,
    chunk_index: int,
    chunk_total: int,
    max_retries: int = MAX_GENERATION_RETRIES,
) -> ChunkExtractionModel:
    """从单段资料提炼做法；失败时有限重试。"""
    return await llm.chat_structured(
        build_chunk_messages(text=text, chunk_index=chunk_index, chunk_total=chunk_total),
        ChunkExtractionModel,
        temperature=0.1,
        max_retries=max_retries,
    )


def build_merge_messages(*, notes: str, hint: str = "") -> list[ChatMessage]:
    """构造合并请求：只基于已提炼的做法，不允许再引入新知识。"""
    return [
        ChatMessage(
            role="system",
            content=render_prompt(
                "skill_merge_chunks.md",
                hint=hint.strip() or "（无）",
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                "请合并下面的做法，输出一个紧凑且可执行的技能 JSON。\n\n"
                f"<做法清单>\n{notes}\n</做法清单>"
            ),
        ),
    ]


async def merge_skill_notes(
    llm: LLMProvider,
    *,
    notes: str,
    hint: str = "",
    max_retries: int = MAX_GENERATION_RETRIES,
) -> SkillDraftModel:
    """把多段做法合并为单个技能草稿；失败时有限重试。"""
    return await llm.chat_structured(
        build_merge_messages(notes=notes, hint=hint),
        SkillDraftModel,
        temperature=0.2,
        max_retries=max_retries,
    )
