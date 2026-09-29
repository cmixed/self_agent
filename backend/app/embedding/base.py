"""Embedding 抽象层。

Embedding Provider 与 LLM Provider 相互独立（AGENTS.md §12）：
更换 Embedding 模型只需新增实现并修改 factory，Agent / RAG 无需改动。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence


class EmbeddingError(Exception):
    """Embedding 层错误基类。"""

    error_type = "embedding_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EmbeddingConfigError(EmbeddingError):
    """Embedding 配置缺失或非法。"""

    error_type = "embedding_config_error"


class EmbeddingProvider(ABC):
    """统一的 Embedding 接口。"""

    name: str = "base"

    def __init__(self, *, model: str, dimension: int) -> None:
        self.model_name = model
        self.dimension = dimension

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """批量向量化文档片段。"""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """向量化查询。"""

    def signature(self) -> dict[str, str | int]:
        """用于记录在向量集合上的 embedding 配置（§12）。"""
        return {
            "provider": self.name,
            "model": self.model_name,
            "dimension": self.dimension,
        }
