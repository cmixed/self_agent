"""基线系统：最朴素的 RAG QA（AGENTS.md §23 对比实验）。

流程只有一步：检索 top-k → 把片段塞进单个 prompt → 让模型回答。

刻意保持简单，用来和 Agent 流程（规划 → 检索 → 大纲 → 逐章写作 → 校验 → 汇总）对比，
体现「多步任务型 Agent」相对「检索问答」的差异。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.llm.base import ChatMessage, LLMProvider
from app.models.state import RetrievedDocument
from app.prompts import render_prompt
from app.rag.tools import RagTool, format_context

_BASELINE_SYSTEM_PROMPT = render_prompt("eval_baseline.md")


@dataclass(frozen=True)
class BaselineResult:
    answer: str
    documents: list[RetrievedDocument]
    llm_calls: int
    duration_seconds: float


async def run_baseline(
    *,
    llm: LLMProvider,
    rag_tool: RagTool,
    query: str,
    top_k: int = 5,
) -> BaselineResult:
    """执行一次基线 RAG QA。"""
    started = time.perf_counter()

    documents = await rag_tool.search(query, top_k=top_k)
    context = format_context(documents) if documents else "（未检索到相关资料）"
    messages = [
        ChatMessage(role="system", content=_BASELINE_SYSTEM_PROMPT),
        ChatMessage(role="user", content=f"资料：\n{context}\n\n问题：{query}"),
    ]
    response = await llm.chat(messages, temperature=0.3)

    return BaselineResult(
        answer=response.content,
        documents=documents,
        llm_calls=1,
        duration_seconds=time.perf_counter() - started,
    )
