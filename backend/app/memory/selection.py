"""选出本次任务值得注入提示词的长期记忆（确定性、无 IO）。

为什么需要筛选：长期记忆会随着长文任务持续累积，如果把「最近若干条」无脑
塞进每个节点，既浪费 token，也会把无关事实变成噪声。这里只做三件轻量的事：

1. 用 query 与记忆的字符二元组 / ASCII 词重合度打分；
2. 用户明确在问自己时（「我的方向」「我平时」…）允许无重合的记忆入选；
3. 按得分、再按新旧排序，最多取 ``MAX_CONTEXT_MEMORIES`` 条。

刻意不引入 LLM / embedding：筛选必须是确定性的，且不能为了选记忆再多一次
模型调用。真正的注入预算由 ``app.agents.memory_context`` 按节点收紧。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.memory.dedupe import normalize_text
from app.memory.repository import MemoryRecord

# 状态里最多保留多少条候选记忆（每个节点还会再按预算取更少）
MAX_CONTEXT_MEMORIES = 6

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")

# 知识库口头语不算「在问用户本人」，否则「根据我的资料写综述」会把所有记忆拉进来。
_KNOWLEDGE_PHRASES = (
    "我的资料",
    "我的文档",
    "我的论文",
    "我的笔记",
    "我的知识库",
    "根据我的资料",
    "根据我的文档",
)

# 归一化后的自我指代片段（normalize_text 会去掉标点/空白）。
_SELF_REFERENCE_MARKERS = (
    "我的方向",
    "我的研究",
    "我的专业",
    "我的背景",
    "我的偏好",
    "我的情况",
    "我的工作",
    "我适合",
    "我之前",
    "我上次",
    "我平时",
    "我习惯",
    "我喜欢",
    "我从事",
    "我在做",
    "我是",
)


def _query_tokens(query: str) -> set[str]:
    """把 query 拆成可比较的有效词：ASCII 词 + 中文二元组。"""
    normalized = normalize_text(query)
    tokens = {token for token in _ASCII_TOKEN_RE.findall(normalized) if len(token) >= 2}
    for run in _CJK_RUN_RE.findall(normalized):
        if len(run) == 2:
            tokens.add(run)
        elif len(run) > 2:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return {token for token in tokens if len(token) >= 2}


def asks_about_user(query: str) -> bool:
    """query 是否在询问用户自身信息（而不是「我的资料」这类知识库指代）。"""
    text = normalize_text(query)
    for phrase in _KNOWLEDGE_PHRASES:
        text = text.replace(normalize_text(phrase), "")
    return any(marker in text for marker in _SELF_REFERENCE_MARKERS)


def select_memories(
    memories: Sequence[MemoryRecord],
    *,
    query: str,
    limit: int = MAX_CONTEXT_MEMORIES,
) -> list[dict[str, str]]:
    """返回最多 ``limit`` 条值得注入的记忆（``{"kind", "content"}``）。

    - 普通任务：只保留与 query 有词重合的记忆，宁缺毋滥；
    - 用户问自己：没有重合时也允许按新旧补足，避免「我的方向是什么」查不到；
    - 同分时新记忆优先（``memory_id`` 递增）。
    """
    if limit <= 0 or not memories:
        return []

    tokens = _query_tokens(query)
    self_reference = asks_about_user(query)

    scored: list[tuple[int, int, MemoryRecord]] = []
    for memory in memories:
        content = memory.content.strip()
        if not content:
            continue
        normalized = normalize_text(content)
        score = sum(1 for token in tokens if token in normalized)
        if score == 0 and not self_reference:
            continue
        scored.append((score, memory.memory_id, memory))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [
        {"kind": memory.kind or "fact", "content": memory.content.strip()}
        for _, _, memory in scored[:limit]
    ]


__all__ = [
    "MAX_CONTEXT_MEMORIES",
    "asks_about_user",
    "select_memories",
]
