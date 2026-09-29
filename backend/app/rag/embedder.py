"""向量化辅助。

负责把文本分批送入 Embedding Provider，避免一次性编码过多文本。
"""

from __future__ import annotations

from collections.abc import Sequence

from app.embedding.base import EmbeddingError, EmbeddingProvider


async def embed_in_batches(
    provider: EmbeddingProvider,
    texts: Sequence[str],
    *,
    batch_size: int = 32,
) -> list[list[float]]:
    """分批向量化，返回与 ``texts`` 等长的向量列表。"""
    if not texts:
        return []
    size = max(1, batch_size)
    vectors: list[list[float]] = []
    for start in range(0, len(texts), size):
        vectors.extend(await provider.embed_documents(list(texts[start : start + size])))
    if len(vectors) != len(texts):
        raise EmbeddingError(f"向量数量与文本数量不一致：{len(vectors)} != {len(texts)}")
    return vectors
