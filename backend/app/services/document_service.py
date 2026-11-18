"""文档服务：上传 → 解析 → 切分 → 向量化 → 入库。

文档处理与 Agent 解耦；Agent 只能通过 RAG Tool 检索（§4.1 / §11）。

团队版改动：文档归属到**知识库**，能否列表 / 打开原文 / 增删改，全部由
``app.services.access`` 的能力并集决定（不再有文档级的 team/private 开关）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.logging import get_logger
from app.embedding.base import EmbeddingProvider
from app.models.schemas import DocumentCaps, DocumentInfo
from app.rag.embedder import embed_in_batches
from app.rag.loader import (
    SUPPORTED_SUFFIXES,
    DocumentLoadError,
    UnsupportedDocumentError,
    load_document,
)
from app.rag.splitter import Chunk, split_pages
from app.rag.store import ChromaStore
from app.services.access import TEAM_KB_ID, Access, AccessService, Caps

logger = get_logger(__name__)


class DocumentNotFoundError(Exception):
    """文档不存在。"""


class DocumentPermissionError(Exception):
    """当前成员无权操作该文档。"""


class DocumentService:
    """知识库文档管理。"""

    def __init__(
        self,
        *,
        provider_factory: Callable[[], EmbeddingProvider],
        store: ChromaStore,
        documents_dir: Path,
        access: AccessService | None = None,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        embed_batch_size: int = 32,
    ) -> None:
        self._provider_factory = provider_factory
        self._store = store
        self._documents_dir = documents_dir
        # 能力判定入口。为 None 时（单元测试 / 内部脚本）不做权限过滤，
        # 与团队版之前的行为一致；HTTP 层始终注入真实实例。
        self._access = access
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._embed_batch_size = embed_batch_size

    # ---------- 能力 ----------

    def _caps(self, user_id: str, is_admin: bool) -> Access | None:
        # getattr：测试里的假服务可能不调用父类 __init__（无 access 即不过滤）
        access = getattr(self, "_access", None)
        if access is None:
            return None
        return access.resolve(user_id, is_admin)

    def document_caps(self, info: dict[str, Any], user_id: str | None, is_admin: bool) -> Caps:
        """某篇文档对某成员的能力；内部调用（无身份）视为全量。"""
        if user_id is None or getattr(self, "_access", None) is None:
            return Caps.of(search=True, list=True, read=True, write=True)
        kb_id = str(info.get("kb_id") or TEAM_KB_ID)
        access = self._caps(user_id, is_admin)
        assert access is not None
        return access.document_caps(kb_id, str(info["document_id"]))

    # ---------- 写入 ----------

    async def ingest(
        self,
        *,
        filename: str,
        content: bytes,
        owner_id: str | None = None,
        kb_id: str = TEAM_KB_ID,
    ) -> DocumentInfo:
        """保存并索引一份文档。失败时回滚，不留下半成品数据。"""
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise UnsupportedDocumentError(f"不支持的文件类型：{suffix or '(无扩展名)'}")
        if not content:
            raise DocumentLoadError("上传内容为空")
        if owner_id is not None and self._access is not None:
            caps = self._caps(owner_id, False)
            assert caps is not None
            if not caps.can(kb_id, "write"):
                raise DocumentPermissionError(kb_id)

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
                metadatas=[
                    self._metadata(document_id, filename, title, chunk, owner_id, kb_id)
                    for chunk in chunks
                ],
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
                "node": f"document_id={document_id} kb_id={kb_id} chunks={len(chunks)}",
            },
        )
        caps = self.document_caps({"document_id": document_id, "kb_id": kb_id}, owner_id, False)
        return DocumentInfo(
            document_id=document_id,
            filename=filename,
            title=title,
            chunks=len(chunks),
            kb_id=kb_id,
            owner_id=owner_id,
            can_manage=caps.write,
            caps=DocumentCaps(**caps.as_dict()),
        )

    # ---------- 读取 ----------

    async def list_documents(
        self,
        *,
        user_id: str | None = None,
        is_admin: bool = False,
        kb_id: str | None = None,
    ) -> list[DocumentInfo]:
        """列出成员可见的文档（按 ``list`` 能力过滤，可按知识库收窄）。

        ``user_id`` 为 None 表示内部调用（导出、备份等），不做过滤。
        """
        access = self._caps(user_id, is_admin) if user_id else None
        documents: list[DocumentInfo] = []
        for item in await self._store.alist_documents():
            item_kb = str(item.get("kb_id") or TEAM_KB_ID)
            if kb_id is not None and item_kb != kb_id:
                continue
            if access is not None:
                caps = access.document_caps(item_kb, str(item["document_id"]))
                if not caps.list:
                    continue
            else:
                caps = Caps.of(search=True, list=True, read=True, write=True)
            documents.append(
                DocumentInfo(
                    document_id=str(item["document_id"]),
                    filename=str(item.get("filename") or ""),
                    title=str(item.get("title") or ""),
                    chunks=int(item.get("chunks") or 0),
                    kb_id=item_kb,
                    owner_id=item.get("owner_id"),
                    can_manage=caps.write,
                    caps=DocumentCaps(**caps.as_dict()),
                )
            )
        return documents

    async def raw_documents(self) -> list[dict[str, Any]]:
        """底层聚合视图（含 kb_id / visibility 等元数据），供迁移与统计使用。"""
        return await self._store.alist_documents()

    async def assign_kb(self, document_id: str, kb_id: str) -> None:
        """只改归属（迁移历史文档用，不校验能力）。"""
        await self._store.aset_document_metadata(document_id, {"kb_id": kb_id})

    async def visible_document_ids(
        self, *, user_id: str, is_admin: bool = False, kb_id: str | None = None
    ) -> set[str]:
        """当前成员可**检索**的文档集合（「仅检索」权限也算）。

        注意与 :meth:`list_documents` 的区别：列表看 ``list`` 能力，检索看
        ``search`` 能力。只有 ``search`` 的成员能在任务里用到这些资料，
        但既看不到文件列表，也打不开原文。
        """
        access = self._caps(user_id, is_admin)
        if access is None:
            return {
                str(item["document_id"])
                for item in await self._store.alist_documents()
                if kb_id is None or str(item.get("kb_id") or TEAM_KB_ID) == kb_id
            }
        visible: set[str] = set()
        for item in await self._store.alist_documents():
            item_kb = str(item.get("kb_id") or TEAM_KB_ID)
            if kb_id is not None and item_kb != kb_id:
                continue
            if access.document_caps(item_kb, str(item["document_id"])).search:
                visible.add(str(item["document_id"]))
        return visible

    async def get_document(
        self,
        document_id: str,
        *,
        user_id: str | None = None,
        is_admin: bool = False,
        need: str = "list",
    ) -> dict[str, Any] | None:
        """按能力读取文档元信息；不满足时返回 None（不泄露存在性）。

        ``need``：``list`` = 能出现在列表里，``read`` = 能打开原文。
        """
        info = await self._store.aget_document(document_id)
        if info is None:
            return None
        if user_id is None:
            return info
        caps = self.document_caps(info, user_id, is_admin)
        return info if caps.has(need) else None  # type: ignore[arg-type]

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

    # ---------- 变更 ----------

    async def move_document(
        self,
        document_id: str,
        *,
        kb_id: str,
        user_id: str,
        is_admin: bool = False,
    ) -> DocumentInfo:
        """把文档移动到另一个知识库（源库与目标库都需要 ``write`` 能力）。"""
        info = await self._store.aget_document(document_id)
        if info is None:
            raise DocumentNotFoundError(document_id)
        source_kb = str(info.get("kb_id") or TEAM_KB_ID)
        if source_kb == kb_id:
            raise ValueError("文档已在该知识库中")
        caps = self.document_caps(info, user_id, is_admin)
        if not caps.write:
            raise DocumentPermissionError(document_id)
        if self._access is not None:
            target = self._caps(user_id, is_admin)
            assert target is not None
            if not target.can(kb_id, "write"):
                raise DocumentPermissionError(kb_id)
        await self._store.aset_document_metadata(document_id, {"kb_id": kb_id})
        refreshed = await self._store.aget_document(document_id)
        assert refreshed is not None
        new_caps = self.document_caps(refreshed, user_id, is_admin)
        return DocumentInfo(
            document_id=str(refreshed["document_id"]),
            filename=str(refreshed.get("filename") or ""),
            title=str(refreshed.get("title") or ""),
            chunks=int(refreshed.get("chunks") or 0),
            kb_id=kb_id,
            owner_id=refreshed.get("owner_id"),
            can_manage=new_caps.write,
            caps=DocumentCaps(**new_caps.as_dict()),
        )

    async def delete_document(
        self, document_id: str, *, user_id: str | None = None, is_admin: bool = False
    ) -> bool:
        info = await self._store.aget_document(document_id)
        if info is None:
            return False
        # 传了身份就校验权限；不传（内部调用 / 测试）保持旧行为
        if user_id is not None and not self.document_caps(info, user_id, is_admin).write:
            raise DocumentPermissionError(document_id)
        await self._store.adelete_document(document_id)
        for path in self._documents_dir.glob(f"{document_id}.*"):
            self._remove_file(path)
        return True

    # ---------- 内部 ----------

    @staticmethod
    def _chunk_id(document_id: str, chunk: Chunk) -> str:
        return f"{document_id}:{chunk.index}"

    @staticmethod
    def _metadata(
        document_id: str,
        filename: str,
        title: str,
        chunk: Chunk,
        owner_id: str | None = None,
        kb_id: str = TEAM_KB_ID,
    ) -> dict[str, Any]:
        """§11 约定的 metadata；page 未知时省略（Chroma 不接受 None）。"""
        metadata: dict[str, Any] = {
            "document_id": document_id,
            "filename": filename,
            "chunk_id": f"{document_id}:{chunk.index}",
            "source": filename,
            "title": title,
            "kb_id": kb_id,
        }
        if owner_id:
            metadata["owner_id"] = owner_id
        if chunk.page is not None:
            metadata["page"] = chunk.page
        return metadata

    @staticmethod
    def _remove_file(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - 清理失败不应掩盖原始错误
            pass
