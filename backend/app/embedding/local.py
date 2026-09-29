"""本地 Embedding Provider（sentence-transformers）。

默认模型 ``BAAI/bge-small-zh-v1.5``：中文检索效果好、体积小，适合个人知识库。
模型推理是 CPU 密集型同步操作，通过 ``asyncio.to_thread`` 让出事件循环。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from app.core.logging import get_logger
from app.embedding.base import EmbeddingConfigError, EmbeddingError, EmbeddingProvider

logger = get_logger(__name__)


class LocalSentenceTransformerEmbedding(EmbeddingProvider):
    """基于 sentence-transformers 的本地 Embedding。"""

    name = "local"

    def __init__(
        self,
        *,
        model: str,
        device: str = "cpu",
        batch_size: int = 32,
        query_instruction: str = "",
        normalize: bool = True,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - 依赖缺失时的兜底
            raise EmbeddingConfigError(
                "未安装 sentence-transformers，无法使用本地 Embedding"
            ) from exc

        self._batch_size = max(1, batch_size)
        self._query_instruction = query_instruction
        self._normalize = normalize

        try:
            # 离线优先：模型已缓存时直接加载，避免 huggingface_hub 的联网检查与
            # time.sleep 重试（无网络时会把事件循环阻塞住）。
            self._st_model = SentenceTransformer(model, device=device, local_files_only=True)
        except Exception:  # noqa: BLE001 - 本地没有缓存时回退到在线下载
            logger.warning(
                "本地未找到 Embedding 模型缓存，改为在线下载",
                extra={"event": "embedding_download", "status": "running", "node": model},
            )
            try:
                self._st_model = SentenceTransformer(model, device=device)
            except Exception as exc:  # noqa: BLE001 - 统一转为本层的配置错误
                raise EmbeddingConfigError(f"加载 Embedding 模型失败：{model}（{exc}）") from exc

        # sentence-transformers 6.x 将方法名改为 get_embedding_dimension
        get_dimension = (
            getattr(self._st_model, "get_embedding_dimension", None)
            or self._st_model.get_sentence_embedding_dimension
        )
        dimension = get_dimension() or 0
        super().__init__(model=model, dimension=int(dimension))

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._encode, list(texts))

    async def embed_query(self, text: str) -> list[float]:
        query = f"{self._query_instruction}{text}" if self._query_instruction else text
        vectors = await asyncio.to_thread(self._encode, [query])
        return vectors[0]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._st_model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=self._normalize,
            show_progress_bar=False,
        )
        result = [list(map(float, vector)) for vector in vectors]
        if len(result) != len(texts):
            raise EmbeddingError(f"Embedding 输出数量与输入不一致：{len(result)} != {len(texts)}")
        return result
