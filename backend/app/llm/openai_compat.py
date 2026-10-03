"""OpenAI Chat Completions 兼容 Provider 基类。

DeepSeek 与 GLM（智谱）都提供 OpenAI 兼容的 ``/chat/completions`` 接口，
因此重试、超时、限流、错误归类等逻辑只需实现一次；具体 Provider 只声明
``name``（协议标识）与 ``display_name``（面向用户的错误信息前缀）。
所有网络细节收敛在本文件内，业务层只看到 :class:`~app.llm.base.LLMError`
的子类（见 AGENTS.md §4.3 / §10 / §25）。
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


class OpenAICompatProvider(LLMProvider):
    """基于 httpx 的 OpenAI 兼容异步 Provider。"""

    name = "openai_compat"
    # 面向用户的显示名（错误信息前缀），子类必须覆盖
    display_name = "OpenAI 兼容服务"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        api_key_env: str = "API_KEY",
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise LLMConfigError(f"{api_key_env} 未配置")

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
                last_error = LLMTimeoutError(f"{self.display_name} 请求超时：{exc}")
            except httpx.HTTPError as exc:
                last_error = LLMUpstreamError(f"{self.display_name} 网络异常：{exc}")
            else:
                if response.status_code == 200:
                    return self._parse_response(response)
                if response.status_code == 429:
                    last_error = LLMRateLimitError(f"{self.display_name} 触发限流（429）")
                elif response.status_code >= 500:
                    last_error = LLMUpstreamError(
                        f"{self.display_name} 服务异常（{response.status_code}）"
                    )
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
            raise LLMUpstreamError(f"{self.display_name} 返回体结构无法解析") from exc

        usage = data.get("usage") or {}
        return LLMResponse(
            content=content,
            model=data.get("model") or self._model,
            usage={k: int(v) for k, v in usage.items() if isinstance(v, int)},
        )

    def _describe_http_error(self, response: httpx.Response) -> str:
        """构造错误描述，绝不包含 Authorization 头或 API Key。"""
        body = response.text[:_MAX_ERROR_BODY_CHARS] if response.text else ""
        suffix = f"：{body}" if body else ""
        return f"{self.display_name} 请求失败（{response.status_code}）{suffix}"

    async def aclose(self) -> None:
        await self._client.aclose()
