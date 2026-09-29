"""Embedding Provider 工厂。

业务代码通过 :func:`get_embedding_provider` 获取，不直接实例化具体实现。
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.embedding.base import EmbeddingConfigError, EmbeddingProvider

_provider: EmbeddingProvider | None = None


def _create_provider(settings: Settings) -> EmbeddingProvider:
    provider = settings.embedding_provider.strip().lower()

    if provider == "local":
        from app.embedding.local import LocalSentenceTransformerEmbedding

        return LocalSentenceTransformerEmbedding(
            model=settings.embedding_model,
            device=settings.embedding_device,
            batch_size=settings.embedding_batch_size,
            query_instruction=settings.embedding_query_instruction,
        )

    raise EmbeddingConfigError(f"不支持的 EMBEDDING_PROVIDER：{settings.embedding_provider}")


def get_embedding_provider() -> EmbeddingProvider:
    """返回进程级缓存的 Embedding Provider（模型只加载一次）。"""
    global _provider
    if _provider is None:
        _provider = _create_provider(get_settings())
    return _provider


def reset_embedding_provider() -> None:
    """仅用于测试：清空缓存。"""
    global _provider
    _provider = None
