"""FastAPI 依赖项。

把 Provider / 服务通过依赖注入提供，测试时可用 ``app.dependency_overrides``
替换为假实现，从而无需真实模型或磁盘数据（见 AGENTS.md §22）。
"""

from __future__ import annotations

from fastapi import Depends

from app.core.config import get_settings
from app.embedding.factory import get_embedding_provider
from app.llm.base import LLMProvider
from app.llm.factory import get_llm
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.services.document_service import DocumentService
from app.services.task_service import TaskService

_store: ChromaStore | None = None
_retriever: Retriever | None = None


def get_llm_provider() -> LLMProvider:
    return get_llm()


def get_task_service(provider: LLMProvider = Depends(get_llm_provider)) -> TaskService:
    settings = get_settings()
    return TaskService(provider, max_retries=settings.max_retries)


def get_chroma_store() -> ChromaStore:
    """进程级缓存的向量集合（避免每次请求重新打开 Chroma）。"""
    global _store
    if _store is None:
        settings = get_settings()
        _store = ChromaStore(
            persist_dir=settings.chroma_dir,
            collection_name=settings.chroma_collection,
            embedding_signature=get_embedding_provider().signature(),
        )
    return _store


def get_document_service(
    store: ChromaStore = Depends(get_chroma_store),
) -> DocumentService:
    settings = get_settings()
    return DocumentService(
        provider=get_embedding_provider(),
        store=store,
        documents_dir=settings.documents_dir,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        embed_batch_size=settings.embedding_batch_size,
    )


def get_retriever(
    store: ChromaStore = Depends(get_chroma_store),
) -> Retriever:
    settings = get_settings()
    return Retriever(get_embedding_provider(), store, top_k=settings.retrieval_top_k)


def reset_rag_state() -> None:
    """仅用于测试：清空 Chroma 与 Embedding 的进程级缓存。"""
    global _store, _retriever
    _store = None
    _retriever = None
