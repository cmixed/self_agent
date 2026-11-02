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
            # 解析与切分是同步 CPU/IO 操作（PDF 解析可达数百毫秒），放到线程里
            pages = await asyncio.to_thread(load_document, path)
            chunks = await asyncio.to_thread(
                split_pages,
                pages,
                chunk_size=self._chunk_size,
                chunk_overlap=self._chunk_overlap,
            )
            if not chunks:
                raise DocumentLoadError("文档切分后没有得到任何文本块")

            # 仅入库需要向量能力：延迟到此处才加载 Embedding 模型。
            # 放到线程里执行：模型加载/下载是阻塞操作，直接调用会卡住事件循环。
            provider = await asyncio.to_thread(self._provider_factory)
            # 先与集合中已有向量比对维度，避免用错模型污染索引（§12）
            await self._store.averify_dimension(provider.dimension)
            texts = [chunk.text for chunk in chunks]
            vectors = await embed_in_batches(provider, texts, batch_size=self._embed_batch_size)
            await self._store.aadd_chunks(
                ids=[self._chunk_id(document_id, chunk) for chunk in chunks],
                documents=texts,
                metadatas=[self._metadata(document_id, filename, title, chunk) for chunk in chunks],
                embeddings=vectors,
            )
        except Exception:
            self._remove_file(path)
            await self._store.adelete_document(document_id)
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

    async def list_documents(self) -> list[DocumentInfo]:
        return [DocumentInfo(**item) for item in await self._store.alist_documents()]

    async def document_file(self, document_id: str) -> tuple[Path, str] | None:
        """返回文档原文件的 ``(路径, 原始文件名)``；文档不存在或原文件缺失时返回 ``None``。"""
        info = await self._store.aget_document(document_id)
        if info is None:
            return None
        matches = sorted(self._documents_dir.glob(f"{document_id}.*"))
        if not matches:
            return None
        return matches[0], str(info["filename"])

    async def read_document_text(self, document_id: str) -> tuple[str, str, str] | None:
        """读取知识库原始全文，返回 ``(filename, title, text)``。

        原文必须来自上传时保存的原文件，而不是 Chroma 中的切片重建：
        - ``.md/.txt`` 直接读原文件；
        - PDF 复用既有 ``load_document`` 解析（放进线程，避免阻塞事件循环）。

        文档不存在、原文件缺失或无法解析时返回 ``None``；调用方据此给出
        可读错误，不要把半截内容当成原文输出。
        """
        resolved = await self.document_file(document_id)
        if resolved is None:
            return None
        path, filename = resolved
        info = await self._store.aget_document(document_id)
        title = str((info or {}).get("title") or Path(filename).stem)
        pages = await asyncio.to_thread(load_document, path)
        text = "\n\n".join(page.text.strip("\n") for page in pages if page.text.strip()).strip()
        if not text:
            return None
        return filename, title, text

    async def delete_document(self, document_id: str) -> bool:
        if await self._store.aget_document(document_id) is None:
            return False
        await self._store.adelete_document(document_id)
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
