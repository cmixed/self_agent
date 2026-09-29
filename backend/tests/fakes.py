"""测试用假 LLM Provider。

所有 Agent / Graph 测试都使用它，绝不依赖真实 DeepSeek API（AGENTS.md §22）。
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence

from app.embedding.base import EmbeddingError, EmbeddingProvider
from app.llm.base import ChatMessage, LLMProvider, LLMResponse

PLAN_PAYLOAD: dict = {
    "goal": "根据资料撰写 RAG 技术综述",
    "needs_retrieval": True,
    "steps": [
        {"id": "research", "type": "retrieval", "description": "检索 RAG 相关资料"},
        {"id": "write", "type": "writing", "description": "撰写综述正文"},
    ],
}
PLAN_JSON = json.dumps(PLAN_PAYLOAD, ensure_ascii=False)
DRAFT_TEXT = "# RAG 技术综述\n\n这是草稿正文。"


class ScriptedProvider(LLMProvider):
    """按顺序返回预设内容的假 Provider。"""

    name = "scripted"

    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        default: str = DRAFT_TEXT,
    ) -> None:
        self._responses = list(responses or [])
        self._default = default
        self.calls: list[list[ChatMessage]] = []
        self.json_modes: list[bool] = []

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        self.json_modes.append(json_mode)
        content = self._responses.pop(0) if self._responses else self._default
        return LLMResponse(content=content, model="scripted", usage={"total_tokens": 1})

    async def aclose(self) -> None:
        return None


class FakeEmbeddingProvider(EmbeddingProvider):
    """确定性的字符袋向量，用于在测试中验证检索行为（不加载真实模型）。

    相同文本得到相同向量，字符重叠越多余弦相似度越高。
    """

    name = "fake"

    def __init__(self, dimension: int = 64) -> None:
        super().__init__(model="fake-embedding", dimension=dimension)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for char in text:
            if not char.isspace():
                vector[ord(char) % self.dimension] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


class FailingEmbeddingProvider(EmbeddingProvider):
    """始终抛错的 Embedding，用于验证入库失败时的事务回滚。"""

    name = "failing"

    def __init__(self) -> None:
        super().__init__(model="failing", dimension=4)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingError("模拟向量化失败")

    async def embed_query(self, text: str) -> list[float]:
        raise EmbeddingError("模拟向量化失败")
