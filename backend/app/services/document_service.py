"""文档服务：上传 → 解析 → 切分 → 向量化 → 入库。

文档处理与 Agent 解耦；Agent 只能通过 RAG Tool 检索（§4.1 / §11）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.logging import get_logger
from app.embedding.base import EmbeddingProvider
from app.models.schemas import DocumentInfo
from app.rag.embedder import embed_in_batches
from app.rag.loader import (
    SUPPORTED_SUFFIXES,
    DocumentLoadError,
    UnsupportedDocumentError,
    load_document,
)
from app.rag.splitter import Chunk, split_pages
from app.rag.store import ChromaStore

logger = get_logger(__name__)


class DocumentService:
    """知识库文档管理。"""

    def __init__(
        self,
        *,
        provider_factory: Callable[[], EmbeddingProvider],
        store: ChromaStore,
        documents_dir: Path,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        embed_batch_size: int = 32,
    ) -> None:
        self._provider_factory = provider_factory
        self._store = store
        self._documents_dir = documents_dir
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._embed_batch_size = embed_batch_size

    async def ingest(self, *, filename: str, content: bytes) -> DocumentInfo:
        """保存并索引一份文档。失败时回滚，不留下半成品数据。"""
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise UnsupportedDocumentError(f"不支持的文件类型：{suffix or '(无扩展名)'}")
        if not content:
            raise DocumentLoadError("上传内容为空")

        document_id = str(uuid4())
        title = Path(filename).stem
        self._documents_dir.mkdir(parents=True, exist_ok=True)
        path = self._documents_dir / f"{document_id}{suffix}"
        path.write_bytes(content)

        try:
            pages = load_document(path)
            chunks = split_pages(
                pages, chunk_size=self._chunk_size, chunk_overlap=self._chunk_overlap
            )
            if not chunks:
                raise DocumentLoadError("文档切分后没有得到任何文本块")

            # 仅入库需要向量能力：延迟到此处才加载 Embedding 模型。
            # 放到线程里执行：模型加载/下载是阻塞操作，直接调用会卡住事件循环。
            provider = await asyncio.to_thread(self._provider_factory)
            # 先与集合中已有向量比对维度，避免用错模型污染索引（§12）
            self._store.verify_dimension(provider.dimension)
            texts = [chunk.text for chunk in chunks]
            vectors = await embed_in_batches(provider, texts, batch_size=self._embed_batch_size)
            self._store.add_chunks(
                ids=[self._chunk_id(document_id, chunk) for chunk in chunks],
                documents=texts,
                metadatas=[self._metadata(document_id, filename, title, chunk) for chunk in chunks],
                embeddings=vectors,
            )
        except Exception:
            self._remove_file(path)
            self._store.delete_document(document_id)
            raise

        logger.info(
            "文档入库",
            extra={
                "event": "document_ingested",
                "status": "ok",
                "node": f"document_id={document_id} chunks={len(chunks)}",
            },
        )
        return DocumentInfo(
            document_id=document_id, filename=filename, title=title, chunks=len(chunks)
        )

    def list_documents(self) -> list[DocumentInfo]:
        return [DocumentInfo(**item) for item in self._store.list_documents()]

    def delete_document(self, document_id: str) -> bool:
        known = any(item["document_id"] == document_id for item in self._store.list_documents())
        if not known:
            return False
        self._store.delete_document(document_id)
        for path in self._documents_dir.glob(f"{document_id}.*"):
            self._remove_file(path)
        return True

    @staticmethod
    def _chunk_id(document_id: str, chunk: Chunk) -> str:
        return f"{document_id}:{chunk.index}"

    @staticmethod
    def _metadata(document_id: str, filename: str, title: str, chunk: Chunk) -> dict[str, Any]:
        """§11 约定的 metadata；page 未知时省略（Chroma 不接受 None）。"""
        metadata: dict[str, Any] = {
            "document_id": document_id,
            "filename": filename,
            "chunk_id": f"{document_id}:{chunk.index}",
            "source": filename,
            "title": title,
        }
        if chunk.page is not None:
            metadata["page"] = chunk.page
        return metadata

    @staticmethod
    def _remove_file(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - 清理失败不应掩盖原始错误
            pass
