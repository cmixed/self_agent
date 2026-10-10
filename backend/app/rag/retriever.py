"""检索器。

Agent 不直接使用本类，而是通过 ``rag/tools.py`` 暴露的 RAG Tool（§4.1 / §11）。
检索结果必须保留 source metadata，便于最终答案引用来源。
"""

from __future__ import annotations

from collections.abc import Sequence

from app.embedding.base import EmbeddingProvider
from app.models.state import RetrievedDocument
from app.rag.store import ChromaStore


class Retriever:
    """基于向量相似度的知识库检索器。"""

    def __init__(
        self,
        provider: EmbeddingProvider,
        store: ChromaStore,
        *,
        top_k: int = 5,
    ) -> None:
        self._provider = provider
        self._store = store
        self._top_k = max(1, top_k)

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: Sequence[str] | None = None,
    ) -> list[RetrievedDocument]:
        """检索；``document_ids`` 非 None 时限定在这些文档内（空列表 → 无结果）。"""
        if not query.strip():
            return []

        embedding = await self._provider.embed_query(query)
        hits = await self._store.aquery(
            embedding=embedding, top_k=top_k or self._top_k, document_ids=document_ids
        )

        documents: list[RetrievedDocument] = []
        for hit in hits:
            metadata = hit.metadata
            # Chroma cosine distance = 1 - 余弦相似度，转换为相似度分数
            score = round(1.0 - hit.distance, 4) if hit.distance is not None else None
            documents.append(
                RetrievedDocument(
                    document_id=str(metadata.get("document_id", "")),
                    filename=str(metadata.get("filename", "")),
                    page=metadata.get("page") if isinstance(metadata.get("page"), int) else None,
                    chunk_id=str(metadata.get("chunk_id", "")),
                    content=hit.content,
                    score=score,
                )
            )
        return documents
