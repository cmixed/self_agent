"""FastAPI 依赖项。

- ``build_*`` 是普通构造函数，服务层与测试都可直接调用；
- ``get_*`` 是给 FastAPI 的依赖包装，测试可用 ``app.dependency_overrides`` 替换。

RAG Tool 通过 ``build_rag_tool`` 延迟创建：不需要检索的任务不会触发
Embedding 模型加载。
"""

from __future__ import annotations

from fastapi import Depends

from app.core.config import get_settings
from app.embedding.factory import get_embedding_provider
from app.llm.base import LLMProvider
from app.llm.factory import get_llm
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.rag.tools import RagTool
from app.services.document_service import DocumentService
from app.services.task_service import TaskService

_store: ChromaStore | None = None


def build_chroma_store() -> ChromaStore:
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


def build_retriever() -> Retriever:
    settings = get_settings()
    return Retriever(get_embedding_provider(), build_chroma_store(), top_k=settings.retrieval_top_k)


def build_rag_tool() -> RagTool:
    return RagTool(build_retriever())


def build_document_service() -> DocumentService:
    settings = get_settings()
    return DocumentService(
        provider=get_embedding_provider(),
        store=build_chroma_store(),
        documents_dir=settings.documents_dir,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        embed_batch_size=settings.embedding_batch_size,
    )


# --- FastAPI 依赖包装 ---


def get_llm_provider() -> LLMProvider:
    return get_llm()


def get_chroma_store() -> ChromaStore:
    return build_chroma_store()


def get_retriever() -> Retriever:
    return build_retriever()


def get_document_service() -> DocumentService:
    return build_document_service()


def get_task_service(provider: LLMProvider = Depends(get_llm_provider)) -> TaskService:
    settings = get_settings()
    return TaskService(
        provider,
        rag_tool_provider=build_rag_tool,
        max_retries=settings.max_retries,
    )


def reset_rag_state() -> None:
    """仅用于测试：清空进程级缓存的向量集合。"""
    global _store
    _store = None
