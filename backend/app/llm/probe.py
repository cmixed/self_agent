"""Provider 连通性探测与模型发现（服务端代理）。

放在 `llm/` 是因为这两件事都属于 Provider 层：直接按 OpenAI 兼容协议
访问 `GET {base_url}/models` 与 `POST {base_url}/chat/completions`。

由后端代理而不是浏览器直连的原因：避免跨域、并且密钥只在服务端出现
（前端永远拿不到明文密钥）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.llm.base import (
    ChatMessage,
    LLMError,
    LLMLocalServiceUnavailableError,
    LLMTimeoutError,
)
from app.llm.openai_compat import OpenAICompatProvider

# 探测是交互式操作，超时短一些，避免界面长时间转圈
_PROBE_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class ProbeResult:
    """探测结果（``ok=False`` 时 ``detail`` 为可展示的原因）。"""

    ok: bool
    detail: str
    latency_ms: int = 0
    models: list[str] | None = None
    reply: str = ""


def _models_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def list_remote_models(
    *, base_url: str, api_key: str = "", transport: httpx.AsyncBaseTransport | None = None
) -> ProbeResult:
    """列出端点可用模型（Ollama / Kimi / DeepSeek / 任意兼容服务都支持）。"""
    if not base_url.strip():
        return ProbeResult(ok=False, detail="未填写接口地址（Base URL）")

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT_SECONDS, transport=transport
        ) as client:
            response = await client.get(_models_url(base_url), headers=_headers(api_key))
    except httpx.HTTPError as exc:
        return ProbeResult(ok=False, detail=_network_detail(base_url, exc))

    latency_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code != 200:
        return ProbeResult(
            ok=False,
            detail=f"获取模型列表失败（HTTP {response.status_code}）：{_short(response.text)}",
            latency_ms=latency_ms,
        )

    try:
        payload = response.json()
    except ValueError:
        return ProbeResult(ok=False, detail="模型列表返回的不是合法 JSON", latency_ms=latency_ms)

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return ProbeResult(
            ok=False, detail="模型列表格式不符合 OpenAI 兼容规范", latency_ms=latency_ms
        )

    models = sorted(
        str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")
    )
    if not models:
        return ProbeResult(ok=False, detail="端点没有返回任何模型", latency_ms=latency_ms)
    return ProbeResult(
        ok=True,
        detail=f"发现 {len(models)} 个模型",
        latency_ms=latency_ms,
        models=models,
    )


async def probe_chat(
    *,
    base_url: str,
    model: str,
    api_key: str = "",
    api_key_env: str = "API_KEY",
    requires_api_key: bool = True,
    is_local: bool = False,
    timeout_seconds: float = _PROBE_TIMEOUT_SECONDS,
    max_retries: int = 0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProbeResult:
    """发一条极小请求验证「地址 + 模型 + 密钥」是否真的可用。"""
    if not base_url.strip():
        return ProbeResult(ok=False, detail="未填写接口地址（Base URL）")
    if not model.strip():
        return ProbeResult(ok=False, detail="未填写模型名")

    try:
        provider = OpenAICompatProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
            api_key_env=api_key_env,
            requires_api_key=requires_api_key,
            is_local=is_local,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
        )
    except LLMError as exc:
        return ProbeResult(ok=False, detail=str(exc))

    started = time.perf_counter()
    try:
        # 32 tokens 足以验证一次往返；思考型模型（qwen3 等）会先把预算花在
        # reasoning 上，预算给太小会拿到空 content（连接其实没问题）
        response = await provider.chat(
            [ChatMessage(role="user", content="ping")], temperature=0.0, max_tokens=32
        )
    except LLMLocalServiceUnavailableError:
        # 本地服务未启动是最常见的失败：给出可操作的具体提示，而不是底层异常文本
        return ProbeResult(
            ok=False, detail=f"无法连接 {base_url}（服务未启动或地址/端口不正确）"
        )
    except LLMTimeoutError:
        return ProbeResult(ok=False, detail=f"连接 {base_url} 超时（{timeout_seconds:.0f}s）")
    except LLMError as exc:
        return ProbeResult(ok=False, detail=str(exc))
    finally:
        await provider.aclose()

    latency_ms = int((time.perf_counter() - started) * 1000)
    reply = _short(response.content, limit=60)
    detail = f"连接成功（{latency_ms} ms）"
    if not reply:
        # 思考型模型可能只输出了思考内容：连接没问题，但要如实说明
        detail = f"连接成功（{latency_ms} ms，模型只输出了思考内容，未返回正文）"
    return ProbeResult(ok=True, detail=detail, latency_ms=latency_ms, reply=reply)


def _network_detail(base_url: str, exc: httpx.HTTPError | None) -> str:
    if isinstance(exc, httpx.ConnectError):
        return f"无法连接 {base_url}（服务未启动或地址/端口不正确）"
    if isinstance(exc, httpx.TimeoutException):
        return f"连接 {base_url} 超时"
    return f"网络异常：{exc}"


def _short(text: str, limit: int = 200) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned[:limit]
