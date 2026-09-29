"""RAG Tool。

Agent 只能通过本工具查询知识库，不得直接操作 ChromaDB（AGENTS.md §4.1 / §11）。
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.state import RetrievedDocument
from app.rag.retriever import Retriever

_MAX_CONTEXT_CHARS_PER_DOCUMENT = 800


class RagTool:
    """暴露给 Agent 的知识库检索工具。"""

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    async def search(self, query: str, *, top_k: int | None = None) -> list[RetrievedDocument]:
        return await self._retriever.retrieve(query, top_k=top_k)


def format_context(
    documents: Sequence[RetrievedDocument],
    *,
    max_chars_per_document: int = _MAX_CONTEXT_CHARS_PER_DOCUMENT,
) -> str:
    """把检索结果渲染成带 [编号] 的上下文，供 Writer 引用。

    编号与最终结果中的 sources 一一对应。
    """
    blocks: list[str] = []
    for index, document in enumerate(documents, start=1):
        page = document.get("page")
        location = f"，第 {page} 页" if page is not None else ""
        content = document.get("content", "")[:max_chars_per_document]
        blocks.append(f"[{index}] 来源：{document.get('filename', '')}{location}\n{content}")
    return "\n\n".join(blocks)
