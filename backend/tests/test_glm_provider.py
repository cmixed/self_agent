"""GLM（智谱）Provider 单元测试。

与 ``test_deepseek_provider.py`` 同构：使用 httpx ``MockTransport``，
不产生真实网络请求（真实 API 见 ``test_smoke_glm.py``）。
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel

from app.llm.base import (
    ChatMessage,
    LLMConfigError,
    LLMResponseFormatError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.llm.glm import DEFAULT_BASE_URL, DEFAULT_MODEL, GLMProvider


def make_provider(handler, **kwargs) -> GLMProvider:
    """构造注入了 MockTransport 的 Provider，不产生真实网络请求。"""
    kwargs.setdefault("max_retries", 2)
    return GLMProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        retry_backoff_seconds=0.0,
        **kwargs,
    )


def success_body(content: str = "hi") -> dict:
    return {
        "model": DEFAULT_MODEL,
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }


def test_provider_requires_api_key() -> None:
    with pytest.raises(LLMConfigError) as exc_info:
        GLMProvider(api_key="   ")
    assert "GLM_API_KEY" in str(exc_info.value)


def test_default_endpoint_is_zhipu_openai_compat() -> None:
    assert DEFAULT_BASE_URL == "https://open.bigmodel.cn/api/paas/v4"
    assert DEFAULT_MODEL == "glm-5.3-flash"
    assert GLMProvider.name == "glm"


async def test_chat_success_parses_content_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path.endswith("/chat/completions")
        assert str(request.url).startswith(DEFAULT_BASE_URL)
        return httpx.Response(200, json=success_body("你好"))

    provider = make_provider(handler)
    try:
        response = await provider.chat([ChatMessage(role="user", content="你好")])
        assert response.content == "你好"
        assert response.model == DEFAULT_MODEL
        assert response.usage["total_tokens"] == 3
    finally:
        await provider.aclose()


async def test_json_mode_sends_response_format() -> None:
    captured: dict = {}

    def capturing_handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, json=success_body('{"ok": true}'))

    provider = make_provider(capturing_handler)
    try:
        await provider.chat(
            [ChatMessage(role="user", content="返回 JSON")], json_mode=True, temperature=0.0
        )
    finally:
        await provider.aclose()

    import json as jsonlib

    sent = jsonlib.loads(captured["body"])
    assert sent["response_format"] == {"type": "json_object"}


async def test_chat_4xx_does_not_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    provider = make_provider(handler)
    try:
        with pytest.raises(LLMUpstreamError):
            await provider.chat([ChatMessage(role="user", content="hi")])
        assert calls["n"] == 1
    finally:
        await provider.aclose()


async def test_chat_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=success_body("ok"))

    provider = make_provider(handler)
    try:
        response = await provider.chat([ChatMessage(role="user", content="hi")])
        assert response.content == "ok"
        assert calls["n"] == 2
    finally:
        await provider.aclose()


async def test_chat_timeout_is_retried_then_raises_timeout() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("boom")

    provider = make_provider(handler, max_retries=1)
    try:
        with pytest.raises(LLMTimeoutError):
            await provider.chat([ChatMessage(role="user", content="hi")])
        assert calls["n"] == 2
    finally:
        await provider.aclose()


async def test_chat_error_message_never_leaks_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    provider = make_provider(handler)
    try:
        with pytest.raises(LLMUpstreamError) as exc_info:
            await provider.chat([ChatMessage(role="user", content="hi")])
        assert "test-key" not in str(exc_info.value)
    finally:
        await provider.aclose()


class _Plan(BaseModel):
    goal: str


async def test_chat_structured_validates_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=success_body('{"goal": "写一篇综述"}'))

    provider = make_provider(handler)
    try:
        plan = await provider.chat_structured([ChatMessage(role="user", content="规划")], _Plan)
        assert plan.goal == "写一篇综述"
    finally:
        await provider.aclose()


async def test_chat_structured_raises_after_limited_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=success_body("这不是 JSON"))

    provider = make_provider(handler)
    try:
        with pytest.raises(LLMResponseFormatError):
            await provider.chat_structured(
                [ChatMessage(role="user", content="规划")], _Plan, max_retries=1
            )
    finally:
        await provider.aclose()
