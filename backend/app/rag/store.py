"""ChromaDB 向量存储封装。

ChromaDB 的访问集中在本模块，Agent 只能通过 RAG Tool 间接使用（§4.1 / §11）。
集合上记录 embedding 配置，更换模型后可检测到不一致（§12）。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.embedding.base import EmbeddingConfigError

_ADD_BATCH_SIZE = 500


@dataclass(frozen=True)
class ChunkHit:
    """一次检索命中的文本块。"""

    content: str
    metadata: dict[str, Any]
    distance: float | None


class ChromaStore:
    """持久化的 Chroma 集合。"""

    def __init__(
        self,
        *,
        persist_dir: Path,
        collection_name: str,
        embedding_signature: dict[str, Any],
    ) -> None:
        import chromadb
        from chromadb.config import Settings

        persist_dir.mkdir(parents=True, exist_ok=True)
        # Chroma 客户端不是为并发访问设计的：所有访问统一串行化，
        # 同时通过 asyncio.to_thread 让出事件循环（见 _run）。
        self._lock = threading.Lock()
        self._collection_name = collection_name
        self._client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=None,
            metadata={
                "hnsw:space": "cosine",
                **{
                    f"embedding_{key}": value
                    for key, value in embedding_signature.items()
                    if value is not None
                },
            },
        )
        self._verify_signature(embedding_signature)

    def _verify_signature(self, embedding_signature: dict[str, Any]) -> None:
        """校验 embedding 配置是否与集合一致。

        只比较本次提供的键，因此调用方可以只声明 ``provider`` / ``model``
        （``dimension`` 需要加载模型才能得知，推迟到首次向量化时再校验/记录）。
        """
        stored = {
            key[len("embedding_") :]: value
            for key, value in (self._collection.metadata or {}).items()
            if key.startswith("embedding_")
        }
        for key, expected in embedding_signature.items():
            if expected is None:
                continue
            actual = stored.get(key)
            if actual is not None and actual != expected:
                raise EmbeddingConfigError(
                    f"集合 {self._collection_name} 的 embedding 配置与当前不一致："
                    f"{key} 已存 {actual}，当前 {expected}。"
                    "更换 Embedding 模型后需要重建索引（更换 collection 名称或清空数据）。"
                )

    def verify_dimension(self, dimension: int) -> None:
        """校验向量维度与集合中已有向量一致。

        维度不写入 metadata：Chroma 的 ``modify`` 会整体替换 metadata
        （丢失 ``hnsw:space`` 与 provider/model），因此改为从已有向量推导维度。
        集合为空时无需校验；非空且不一致说明更换了 Embedding 模型，必须重建索引。
        """
        if self._collection.count() == 0:
            return
        result = self._collection.get(limit=1, include=["embeddings"])
        embeddings = result.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            return

        stored = len(embeddings[0])
        if stored != int(dimension):
            raise EmbeddingConfigError(
                f"集合 {self._collection_name} 中已有向量的维度为 {stored}，"
                f"当前 Embedding 模型输出 {dimension} 维；"
                "更换 Embedding 模型后需要重建索引（更换 collection 名称或清空数据）。"
            )

    async def _run(self, call, /, *args, **kwargs):
        """在线程中执行一次 Chroma 调用，并用同一把锁串行化。

        直接调用会阻塞事件循环（实测入库 220 块约 190ms，且随块数线性增长），
        阻塞期间所有并发请求（含 SSE 任务流）都会被拖住。
        """

        def invoke():
            with self._lock:
                return call(*args, **kwargs)

        return await asyncio.to_thread(invoke)

    # --- 异步接口（业务层只应使用这些）---

    async def aquery(self, *, embedding, top_k: int, document_ids=None):
        return await self._run(
            self.query, embedding=embedding, top_k=top_k, document_ids=document_ids
        )

    async def alist_documents(self) -> list[dict[str, Any]]:
        return await self._run(self.list_documents)

    async def aget_document(self, document_id: str) -> dict[str, Any] | None:
        """按 document_id 精确查询（避免为单个文档全量扫描所有 chunk 元数据）。"""
        return await self._run(self.get_document, document_id)

    async def aadd_chunks(self, **kwargs) -> None:
        await self._run(self.add_chunks, **kwargs)

    async def adelete_document(self, document_id: str) -> None:
        await self._run(self.delete_document, document_id)

    async def averify_dimension(self, dimension: int) -> None:
        await self._run(self.verify_dimension, dimension)

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        """返回单个文档的聚合信息；不存在时 None。"""
        result = self._collection.get(
            where={"document_id": document_id}, include=["metadatas"]
        )
        metadatas = [meta for meta in (result.get("metadatas") or []) if meta]
        if not metadatas:
            return None
        first = metadatas[0]
        return {
            "document_id": document_id,
            "filename": first.get("filename", ""),
            "title": first.get("title", ""),
            "chunks": len(metadatas),
        }

    def add_chunks(
        self,
        *,
        ids: Sequence[str],
        documents: Sequence[str],
        metadatas: Sequence[dict[str, Any]],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        for start in range(0, len(ids), _ADD_BATCH_SIZE):
            stop = start + _ADD_BATCH_SIZE
            self._collection.add(
                ids=list(ids[start:stop]),
                documents=list(documents[start:stop]),
                metadatas=[dict(meta) for meta in metadatas[start:stop]],
                embeddings=[list(vector) for vector in embeddings[start:stop]],
            )

    def delete_document(self, document_id: str) -> None:
        self._collection.delete(where={"document_id": document_id})

    def list_documents(self) -> list[dict[str, Any]]:
        """按 document_id 聚合出已入库文档。"""
        result = self._collection.get(include=["metadatas"])
        aggregated: dict[str, dict[str, Any]] = {}
        for metadata in result.get("metadatas") or []:
            if not metadata:
                continue
            document_id = str(metadata.get("document_id", ""))
            if not document_id:
                continue
            entry = aggregated.setdefault(
                document_id,
                {
                    "document_id": document_id,
                    "filename": metadata.get("filename", ""),
                    "title": metadata.get("title", ""),
                    "chunks": 0,
                },
            )
            entry["chunks"] += 1
        return sorted(aggregated.values(), key=lambda item: item["filename"])

    def query(
        self,
        *,
        embedding: Sequence[float],
        top_k: int,
        document_ids: Sequence[str] | None = None,
    ) -> list[ChunkHit]:
        """向量检索；``document_ids`` 非 None 时只在该范围内检索。

        注意：**空列表表示"范围内没有文档"，必须返回空结果**，
        绝不能退化成"不过滤"（否则会检索到范围外的资料）。
        """
        if document_ids is not None and not document_ids:
            return []
        if self._collection.count() == 0:
            return []
        where = (
            {"document_id": {"$in": list(document_ids)}}
            if document_ids is not None
            else None
        )
        result = self._collection.query(
            query_embeddings=[list(embedding)],
            n_results=max(1, top_k),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: list[ChunkHit] = []
        for index, content in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) else {}
            distance = distances[index] if index < len(distances) else None
            hits.append(
                ChunkHit(
                    content=content or "",
                    metadata=dict(metadata or {}),
                    distance=float(distance) if distance is not None else None,
                )
            )
        return hits

    def count(self) -> int:
        return self._collection.count()
