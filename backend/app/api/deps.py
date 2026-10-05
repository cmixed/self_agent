"""FastAPI 依赖项。

- ``build_*`` 是普通构造函数，服务层与测试都可直接调用；
- ``get_*`` 是给 FastAPI 的依赖包装，测试可用 ``app.dependency_overrides`` 替换。

RAG Tool 通过 ``build_rag_tool`` 延迟创建：不需要检索的任务不会触发
Embedding 模型加载。
"""

from __future__ import annotations

from fastapi import Depends, Header
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.core import task_registry as core_task_registry
from app.core.checkpoint import CheckpointStore
from app.core.config import get_settings
from app.core.task_registry import TaskRegistry
from app.embedding.factory import get_embedding_provider
from app.llm.base import LLMProvider
from app.llm.factory import get_llm
from app.memory.repository import MemoryRepository, SkillRepository, TaskRepository
from app.memory.sqlite import SqliteDatabase
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.rag.tools import RagTool
from app.services.document_service import DocumentService
from app.services.memory_service import MemoryService
from app.services.preset_service import PresetService
from app.services.skill_service import SkillService
from app.services.task_service import TaskService

_store: ChromaStore | None = None
_task_repository: TaskRepository | None = None
_memory_repository: MemoryRepository | None = None
_skill_repository: SkillRepository | None = None
_database: SqliteDatabase | None = None
_checkpoint_store: CheckpointStore | None = None


def build_chroma_store() -> ChromaStore:
    """进程级缓存的向量集合（避免每次请求重新打开 Chroma）。

    这里只用**配置**构造签名，不加载 Embedding 模型：
    向量维度推迟到首次入库时由 :meth:`ChromaStore.ensure_dimension` 记录/校验，
    因此「列出文档」「删除文档」等操作不会触发 100MB 模型的加载。
    """
    global _store
    if _store is None:
        settings = get_settings()
        _store = ChromaStore(
            persist_dir=settings.chroma_dir,
            collection_name=settings.chroma_collection,
            embedding_signature={
                "provider": settings.embedding_provider.strip().lower(),
                "model": settings.embedding_model,
            },
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
        provider_factory=get_embedding_provider,
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


def build_database() -> SqliteDatabase:
    """进程级缓存的 SQLite 数据库句柄。"""
    global _database
    if _database is None:
        _database = SqliteDatabase(get_settings().sqlite_path)
    return _database


def build_checkpoint_store() -> CheckpointStore:
    """构造（不启动）Checkpoint 存储；生命周期由应用 lifespan 管理。"""
    global _checkpoint_store
    if _checkpoint_store is None:
        _checkpoint_store = CheckpointStore(get_settings().checkpoint_path)
    return _checkpoint_store


def get_checkpoint_store() -> CheckpointStore | None:
    return _checkpoint_store


def get_checkpointer() -> BaseCheckpointSaver | None:
    store = get_checkpoint_store()
    return store.saver if store is not None else None


def build_task_repository() -> TaskRepository:
    global _task_repository
    if _task_repository is None:
        _task_repository = TaskRepository(build_database())
    return _task_repository


def build_memory_repository() -> MemoryRepository:
    global _memory_repository
    if _memory_repository is None:
        _memory_repository = MemoryRepository(build_database())
    return _memory_repository


def build_skill_repository() -> SkillRepository:
    global _skill_repository
    if _skill_repository is None:
        _skill_repository = SkillRepository(build_database())
    return _skill_repository


def build_skill_service() -> SkillService:
    return SkillService(build_database())


def build_preset_service() -> PresetService:
    return PresetService(build_database())


def get_user_id(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> str:
    """无复杂用户系统（§31）：默认单用户，可通过请求头覆盖。"""
    settings = get_settings()
    candidate = (x_user_id or "").strip()
    return candidate or settings.default_user_id


async def get_task_service(provider: LLMProvider = Depends(get_llm_provider)) -> TaskService:
    settings = get_settings()
    # 技能目录在任务开始时快照（运行中修改技能不影响本次任务）
    skills = await build_skill_service().enabled_skills()
    catalog = [
        {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
        }
        for skill in skills
    ]
    return TaskService(
        provider,
        rag_tool_provider=build_rag_tool,
        skill_catalog=catalog,
        repository=build_task_repository(),
        checkpointer=get_checkpointer(),
        max_retries=settings.max_retries,
        target_sections=settings.effective_target_sections,
        max_sections=settings.effective_max_sections,
        target_total_chars=settings.effective_total_chars,
    )


def get_task_repository() -> TaskRepository:
    return build_task_repository()


def get_task_registry() -> TaskRegistry:
    """FastAPI 依赖：进程内运行任务注册表（测试可用 dependency_overrides 替换）。"""
    return core_task_registry.get_task_registry()


def get_memory_repository() -> MemoryRepository:
    return build_memory_repository()


def get_skill_service() -> SkillService:
    return build_skill_service()


def get_preset_service() -> PresetService:
    return build_preset_service()


def get_memory_service(
    provider: LLMProvider = Depends(get_llm_provider),
) -> MemoryService:
    return MemoryService(build_memory_repository(), provider)


def reset_caches() -> None:
    """仅用于测试：清空进程级缓存的向量集合与持久化句柄。"""
    global _store, _task_repository, _memory_repository, _skill_repository, _database
    _store = None
    _task_repository = None
    _memory_repository = None
    _skill_repository = None
    _database = None
