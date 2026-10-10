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

from app.core.logging import get_logger
from app.llm.base import (
    ChatMessage,
    LLMConfigError,
    LLMLocalInferenceError,
    LLMLocalServiceUnavailableError,
    LLMProvider,
    LLMQuotaError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    LLMUpstreamError,
)

logger = get_logger(__name__)

_CHAT_COMPLETIONS_PATH = "/chat/completions"
_MAX_ERROR_BODY_CHARS = 300

# 余额/配额不足的上游标识：智谱 code=1113（"余额不足或无可用资源包"）、
# OpenAI 风格 code=insufficient_quota，以及常见中英文措辞兜底。
_QUOTA_CODES = frozenset({"1113", "insufficient_quota", "quota_exceeded", "insufficient_balance"})
_QUOTA_KEYWORDS = (
    "余额不足",
    "无可用资源包",
    "欠费",
    "配额不足",
    "insufficient quota",
    "exceeded your current quota",
    "insufficient balance",
)


def _rejects_response_format(response: httpx.Response) -> bool:
    """该 400 是否因为端点不支持 ``response_format``。

    只在错误体明确提到 response_format 时才回退：否则会把真正的请求错误
    （例如模型名拼错）也当成"参数不支持"，掩盖真实原因。
    """
    try:
        text = response.text or ""
    except Exception:  # pragma: no cover - 读取响应体失败时保守处理
        return False
    return "response_format" in text.lower()


def _is_quota_exhausted(response: httpx.Response) -> bool:
    """判断 429 响应是否表示账户余额/配额不足（而非普通限流）。

    只读取错误体的 code 与 message 字段做匹配，不依赖具体厂商结构；
    解析失败时按普通限流处理（保守：宁可重试，也不误判为余额不足）。
    """
    try:
        data = response.json()
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False

    error = data.get("error")
    if not isinstance(error, dict):
        error = data

    code = str(error.get("code") or "").strip().lower()
    if code in _QUOTA_CODES:
        return True

    message = str(error.get("message") or "").lower()
    return any(keyword in message for keyword in _QUOTA_KEYWORDS)


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
        requires_api_key: bool = True,
        is_local: bool = False,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # 本地服务（Ollama 等）不需要密钥：requires_api_key=False 时不发 Authorization
        if requires_api_key and (not api_key or not api_key.strip()):
            raise LLMConfigError(f"{api_key_env} 未配置")

        self._api_key = (api_key or "").strip()
        self._model = model
        # 本地服务的错误提示与默认超时不同，需要业务层能区分
        self.is_local = is_local
        # 部分自定义端点不支持 response_format：探测结果缓存到实例，避免每次多一次往返
        self._json_mode_supported: bool | None = None
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = retry_backoff_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    def _local_unavailable(self, exc: Exception) -> LLMLocalServiceUnavailableError:
        return LLMLocalServiceUnavailableError(f"{self.display_name} 无法连接：{exc}")

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
        # 已知该端点不支持 response_format 时不再携带（首次探测失败后置 False）
        if json_mode and self._json_mode_supported is not False:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        last_error: Exception | None = None
        attempt = 0
        # 「去掉 response_format 再试一次」不占用重试预算（自定义端点兼容性）
        json_fallback_available = True
        while attempt <= self._max_retries:
            try:
                response = await self._client.post(
                    _CHAT_COMPLETIONS_PATH, json=payload, headers=headers
                )
            except httpx.TimeoutException as exc:
                if self.is_local and isinstance(exc, httpx.ConnectTimeout):
                    raise self._local_unavailable(exc) from exc
                last_error = LLMTimeoutError(f"{self.display_name} 请求超时：{exc}")
            except httpx.ConnectError as exc:
                # 本地服务连不上（未启动/端口不对）：重试无意义，直接给出可操作提示
                if self.is_local:
                    raise self._local_unavailable(exc) from exc
                last_error = LLMUpstreamError(f"{self.display_name} 网络异常：{exc}")
            except httpx.HTTPError as exc:
                last_error = LLMUpstreamError(f"{self.display_name} 网络异常：{exc}")
            else:
                if response.status_code == 200:
                    if json_mode:
                        self._json_mode_supported = "response_format" in payload
                    return self._parse_response(response)
                if (
                    response.status_code == 400
                    and json_fallback_available
                    and "response_format" in payload
                    and _rejects_response_format(response)
                ):
                    # 该端点不支持 response_format：去掉参数后用纯提示词 JSON 模式重试，
                    # 结构化仍由 Schema 校验 + 有限重试兜底（见 LLMProvider.chat_structured）
                    payload.pop("response_format", None)
                    json_fallback_available = False
                    self._json_mode_supported = False
                    logger.warning(
                        "端点不支持 response_format，已回退为纯提示词 JSON 模式",
                        extra={"node": self.display_name, "event": "json_mode_fallback"},
                    )
                    continue
                if response.status_code == 429:
                    # 429 语义有两类：真限流（可退避重试）与账户余额/配额不足
                    # （重试无意义）。后者必须区分出来，否则前端会一直提示
                    # 「限流，请稍后重试」而用户永远等不到成功。
                    if _is_quota_exhausted(response):
                        raise LLMQuotaError(
                            f"{self.display_name} 账户余额或配额不足，请充值或更换 Provider"
                        )
                    last_error = LLMRateLimitError(f"{self.display_name} 触发限流（429）")
                elif response.status_code >= 500:
                    detail = self._describe_http_error(response)
                    if self.is_local:
                        # 本地 5xx 多为上下文/显存问题：直接抛出，不浪费重试预算
                        logger.warning(
                            "本地模型推理失败",
                            extra={
                                "node": self.display_name,
                                "event": "local_inference_failed",
                                "status": str(response.status_code),
                            },
                        )
                        raise LLMLocalInferenceError(detail)
                    last_error = LLMUpstreamError(
                        f"{self.display_name} 服务异常（{response.status_code}）"
                    )
                else:
                    # 4xx 多为请求/鉴权问题，重试无意义，直接抛出
                    raise LLMUpstreamError(self._describe_http_error(response))

            if attempt < self._max_retries:
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
            attempt += 1

        assert last_error is not None
        raise last_error

    def _parse_response(self, response: httpx.Response) -> LLMResponse:
        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUpstreamError(f"{self.display_name} 返回体结构无法解析") from exc

        usage = data.get("usage") or {}
        finish_reason = choice.get("finish_reason")
        return LLMResponse(
            content=content,
            model=data.get("model") or self._model,
            usage={k: int(v) for k, v in usage.items() if isinstance(v, int)},
            finish_reason=str(finish_reason) if finish_reason else None,
        )

    def _describe_http_error(self, response: httpx.Response) -> str:
        """构造错误描述，绝不包含 Authorization 头或 API Key。"""
        body = response.text[:_MAX_ERROR_BODY_CHARS] if response.text else ""
        suffix = f"：{body}" if body else ""
        return f"{self.display_name} 请求失败（{response.status_code}）{suffix}"

    async def aclose(self) -> None:
        await self._client.aclose()
