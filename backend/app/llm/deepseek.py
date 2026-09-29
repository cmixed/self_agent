"""DeepSeek Provider。

DeepSeek API 与 OpenAI Chat Completions 兼容，因此这里直接调用
``/chat/completions``。所有网络、超时、限流、错误归类都在本文件内完成，
业务层只看到 :class:`~app.llm.base.LLMError` 的子类。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import httpx

from app.llm.base import (
    ChatMessage,
    LLMConfigError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    LLMUpstreamError,
)

_CHAT_COMPLETIONS_PATH = "/chat/completions"
_MAX_ERROR_BODY_CHARS = 300


class DeepSeekProvider(LLMProvider):
    """基于 httpx 的 DeepSeek 异步 Provider。"""

    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-flash",
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise LLMConfigError("DEEPSEEK_API_KEY 未配置")

        self._api_key = api_key.strip()
        self._model = model
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = retry_backoff_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {self._api_key}"}

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(
                    _CHAT_COMPLETIONS_PATH, json=payload, headers=headers
                )
            except httpx.TimeoutException as exc:
                last_error = LLMTimeoutError(f"DeepSeek 请求超时：{exc}")
            except httpx.HTTPError as exc:
                last_error = LLMUpstreamError(f"DeepSeek 网络异常：{exc}")
            else:
                if response.status_code == 200:
                    return self._parse_response(response)
                if response.status_code == 429:
                    last_error = LLMRateLimitError("DeepSeek 触发限流（429）")
                elif response.status_code >= 500:
                    last_error = LLMUpstreamError(f"DeepSeek 服务异常（{response.status_code}）")
                else:
                    # 4xx 多为请求/鉴权问题，重试无意义，直接抛出
                    raise LLMUpstreamError(self._describe_http_error(response))

            if attempt < self._max_retries:
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))

        assert last_error is not None
        raise last_error

    def _parse_response(self, response: httpx.Response) -> LLMResponse:
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUpstreamError("DeepSeek 返回体结构无法解析") from exc

        usage = data.get("usage") or {}
        return LLMResponse(
            content=content,
            model=data.get("model") or self._model,
            usage={k: int(v) for k, v in usage.items() if isinstance(v, int)},
        )

    @staticmethod
    def _describe_http_error(response: httpx.Response) -> str:
        """构造错误描述，绝不包含 Authorization 头或 API Key。"""
        body = response.text[:_MAX_ERROR_BODY_CHARS] if response.text else ""
        suffix = f"：{body}" if body else ""
        return f"DeepSeek 请求失败（{response.status_code}）{suffix}"

    async def aclose(self) -> None:
        await self._client.aclose()
