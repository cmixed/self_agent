"""测试用假 LLM Provider。

所有 Agent / Graph 测试都使用它，绝不依赖真实 DeepSeek API（AGENTS.md §22）。
"""

from __future__ import annotations

import json
from collections.abc import Sequence

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
