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

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: Sequence[str] | None = None,
    ) -> list[RetrievedDocument]:
        return await self._retriever.retrieve(query, top_k=top_k, document_ids=document_ids)


def dedupe_documents(documents: Sequence[RetrievedDocument]) -> list[RetrievedDocument]:
    """按 ``chunk_id`` 去重，作为 **引用编号的唯一来源**。

    ``format_context``（作家看到的可引用列表）、``render_references``（最终
    「参考来源」）与任务结果里的 ``sources`` 必须共用同一份去重结果，否则
    三者编号会错位，产生「正文引用 [5] 但来源列表只有 4 条」这类悬空引用。
    ``chunk_id`` 为空时不参与去重（保持原有行为）。
    """
    seen: set[str] = set()
    unique: list[RetrievedDocument] = []
    for document in documents:
        chunk_id = document.get("chunk_id", "")
        if chunk_id and chunk_id in seen:
            continue
        if chunk_id:
            seen.add(chunk_id)
        unique.append(document)
    return unique


def format_context(
    documents: Sequence[RetrievedDocument],
    *,
    max_chars_per_document: int = _MAX_CONTEXT_CHARS_PER_DOCUMENT,
) -> str:
    """把检索结果渲染成带 [编号] 的上下文，供 Writer 引用。

    编号与最终结果中的 sources、以及「参考来源」小节一一对应（统一去重）。
    """
    blocks: list[str] = []
    for index, document in enumerate(dedupe_documents(documents), start=1):
        page = document.get("page")
        location = f"，第 {page} 页" if page is not None else ""
        content = document.get("content", "")[:max_chars_per_document]
        blocks.append(f"[{index}] 来源：{document.get('filename', '')}{location}\n{content}")
    return "\n\n".join(blocks)


def render_references(documents: Sequence[RetrievedDocument], *, heading: bool = True) -> str:
    """渲染「参考来源」列表。

    编号规则与 :func:`format_context` 及任务结果中的 ``sources`` 保持一致
    （统一走 :func:`dedupe_documents`）。

    ``heading=False`` 用于简洁回答：保留来源列表，但不额外生成一个 Markdown 标题。
    """
    lines: list[str] = []
    for index, document in enumerate(dedupe_documents(documents), start=1):
        page = document.get("page")
        location = f"（第 {page} 页）" if page is not None else ""
        lines.append(f"[{index}] {document.get('filename', '')}{location}")
    if not lines:
        return ""
    prefix = "## 参考来源\n" if heading else "参考来源：\n"
    return prefix + "\n".join(lines)
