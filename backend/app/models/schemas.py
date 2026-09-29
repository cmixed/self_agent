"""API 请求 / 响应模型。

API 契约与 LLM 内部模型解耦：这里不直接复用 ``app.llm.base.ChatMessage``，
以便接口结构独立演进。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]


class ChatMessageIn(BaseModel):
    role: Role
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """Phase 1 最小请求体：一段对话消息列表。"""

    messages: list[ChatMessageIn] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)


class ChatResponse(BaseModel):
    answer: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    app_env: str
    llm_provider: str
    llm_configured: bool


class ErrorResponse(BaseModel):
    """统一错误结构。``detail`` 只包含可安全展示的信息。"""

    error: str
    error_type: str
    detail: str | None = None
