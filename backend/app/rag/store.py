"""ChromaDB 向量存储封装。

ChromaDB 的访问集中在本模块，Agent 只能通过 RAG Tool 间接使用（§4.1 / §11）。
集合上记录 embedding 配置，更换模型后可检测到不一致（§12）。
"""

from __future__ import annotations

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
        embedding_signature: dict[str, str | int],
    ) -> None:
        import chromadb
        from chromadb.config import Settings

        persist_dir.mkdir(parents=True, exist_ok=True)
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
                **{f"embedding_{key}": value for key, value in embedding_signature.items()},
            },
        )
        self._verify_signature(embedding_signature)

    def _verify_signature(self, embedding_signature: dict[str, str | int]) -> None:
        stored = {
            key[len("embedding_") :]: value
            for key, value in (self._collection.metadata or {}).items()
            if key.startswith("embedding_")
        }
        if stored and stored != dict(embedding_signature):
            raise EmbeddingConfigError(
                f"集合 {self._collection_name} 的 embedding 配置与当前不一致："
                f"已存 {stored}，当前 {dict(embedding_signature)}。"
                "更换 Embedding 模型后需要重建索引（更换 collection 名称或清空数据）。"
            )

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

    def query(self, *, embedding: Sequence[float], top_k: int) -> list[ChunkHit]:
        if self._collection.count() == 0:
            return []
        result = self._collection.query(
            query_embeddings=[list(embedding)],
            n_results=max(1, top_k),
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
