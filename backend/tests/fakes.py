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
OUTLINE_PAYLOAD: dict = {
    "sections": [{"title": "引言"}, {"title": "chunk 大小的影响"}],
}
OUTLINE_JSON = json.dumps(OUTLINE_PAYLOAD, ensure_ascii=False)
DRAFT_TEXT = (
    "# RAG 技术综述\n\n"
    "检索增强生成（RAG）把外部知识库的检索结果注入生成模型，"
    "让回答能够引用用户资料。它的核心环节包括文档切分、向量化、"
    "相似度检索和上下文拼接。合理的 chunk 大小与重叠比例会直接影响"
    "召回质量，而引用编号则用于把生成内容与原始来源对应起来。"
)
VALIDATION_PASS_PAYLOAD: dict = {
    "passed": True,
    "issues": [],
    "suggested_action": "continue",
}
VALIDATION_PASS_JSON = json.dumps(VALIDATION_PASS_PAYLOAD, ensure_ascii=False)


def validation_fail_json(action: str = "retry_writer", issues: list[str] | None = None) -> str:
    return json.dumps(
        {
            "passed": False,
            "issues": issues or ["内容过于空泛"],
            "suggested_action": action,
        },
        ensure_ascii=False,
    )


class ScriptedProvider(LLMProvider):
    """按顺序返回预设内容的假 Provider。

    预设响应按调用顺序消费；用完后按调用模式回退到 ``default_json``
    （结构化调用）或 ``default_text``（普通生成）。
    """

    name = "scripted"

    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        default: str | None = None,
        default_text: str = DRAFT_TEXT,
        default_json: str = VALIDATION_PASS_JSON,
        finish_reasons: list[str | None] | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._default = default
        self._default_text = default_text
        self._default_json = default_json
        self._finish_reasons = list(finish_reasons or [])
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
        if self._responses:
            content = self._responses.pop(0)
        elif self._default is not None:
            content = self._default
        else:
            content = self._default_json if json_mode else self._default_text
        finish_reason = self._finish_reasons.pop(0) if self._finish_reasons else None
        return LLMResponse(
            content=content,
            model="scripted",
            usage={"total_tokens": 1},
            finish_reason=finish_reason,
        )

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


async def seed_knowledge_base(tmp_path, *, text: str, top_k: int = 3):
    """建一个临时知识库并写入一段文本，返回 (store, rag_tool)。"""
    from pathlib import Path

    from app.rag.retriever import Retriever
    from app.rag.store import ChromaStore
    from app.rag.tools import RagTool
    from app.services.document_service import DocumentService

    root = Path(tmp_path)
    provider = FakeEmbeddingProvider()
    store = ChromaStore(
        persist_dir=root / "chroma",
        collection_name="test_kb",
        embedding_signature=provider.signature(),
    )
    service = DocumentService(
        provider_factory=lambda: provider,
        store=store,
        documents_dir=root / "documents",
        chunk_size=200,
        chunk_overlap=20,
    )
    await service.ingest(filename="rag.md", content=text.encode())
    return store, RagTool(Retriever(provider, store, top_k=top_k))
