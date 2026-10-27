"""LLM 用量采集：token 消耗、缓存命中、调用耗时与输出速度。

为什么在 Provider 层采集，而不是每个 Agent 节点各自统计：

- Agent 里有 10+ 处 ``chat`` / ``chat_structured`` 调用，而且
  ``chat_structured`` 内部还有有限重试；逐点采集既容易漏计，也会把
  计量逻辑混进业务代码（AGENTS.md §28）。
- 用一个装饰器包住 Provider，所有节点自动覆盖，Agent Graph / State 不变。

作用域用 :class:`contextvars.ContextVar`：同一次任务运行（含并发的多个 SSE
连接）各自持有自己的 collector，互不干扰；没有作用域时（如 ``/api/chat``
单次调用）记录函数直接 no-op。

口径说明：

- ``prompt_tokens`` / ``completion_tokens`` / ``total_tokens``：上游 ``usage``
  原样累加（Ollama 原生协议只有前两项，总量由二者相加补齐）；
- ``cache_hit_tokens``：DeepSeek 的 ``prompt_cache_hit_tokens`` 或
  OpenAI/GLM 的 ``prompt_tokens_details.cached_tokens``；
- ``llm_seconds``：每次调用的墙钟时间（含网络与排队），
  ``tokens_per_second = completion_tokens / llm_seconds``，
  是「含网络的输出吞吐」，不是纯生成速度（非流式请求拿不到 TTFT）。
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.llm.base import ChatMessage, LLMProvider, LLMResponse

# DeepSeek 与 OpenAI/GLM 的缓存命中字段不同，统一映射到规范键
_DEEPSEEK_CACHE_HIT = "prompt_cache_hit_tokens"
_DEEPSEEK_CACHE_MISS = "prompt_cache_miss_tokens"
_NESTED_DETAILS = "prompt_tokens_details"
_NESTED_CACHED = "cached_tokens"


def _as_int(value: Any) -> int | None:
    """只接受真正的整数（bool 是 int 子类，需排除）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def parse_usage(raw: Mapping[str, Any]) -> dict[str, int]:
    """把上游 ``usage`` 解析成扁平整数表，并补上规范的缓存命中键。

    保留上游已有的整数键（向后兼容 ``/api/chat`` 的返回结构），
    同时把嵌套的 ``prompt_tokens_details.cached_tokens`` 提为
    ``cache_hit_tokens`` —— 原实现只保留顶层 int，嵌套字段会被丢弃。
    """
    usage: dict[str, int] = {}
    if not isinstance(raw, Mapping):
        return usage
    for key, value in raw.items():
        parsed = _as_int(value)
        if parsed is not None:
            usage[key] = parsed

    details = raw.get(_NESTED_DETAILS)
    if isinstance(details, Mapping):
        cached = _as_int(details.get(_NESTED_CACHED))
        if cached is not None:
            usage["cache_hit_tokens"] = cached

    deepseek_hit = _as_int(raw.get(_DEEPSEEK_CACHE_HIT))
    if deepseek_hit is not None:
        usage["cache_hit_tokens"] = deepseek_hit
    deepseek_miss = _as_int(raw.get(_DEEPSEEK_CACHE_MISS))
    if deepseek_miss is not None:
        usage["cache_miss_tokens"] = deepseek_miss

    return usage


class UsageCollector:
    """一次任务运行的用量累加器（只在当前 context 内可见）。"""

    def __init__(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.cache_hit_tokens = 0
        self.cache_miss_tokens = 0
        # 上游是否真的上报过缓存字段：区分「命中 0」与「不提供该指标」
        self.cache_reported = False
        self.llm_seconds = 0.0
        self.models: list[str] = []

    def record(self, response: LLMResponse, elapsed_seconds: float) -> None:
        usage = response.usage or {}
        prompt = _as_int(usage.get("prompt_tokens")) or 0
        completion = _as_int(usage.get("completion_tokens")) or 0
        total = _as_int(usage.get("total_tokens")) or (prompt + completion)

        self.calls += 1
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total
        self.llm_seconds += max(elapsed_seconds, 0.0)

        hit = _as_int(usage.get("cache_hit_tokens"))
        if hit is not None:
            self.cache_reported = True
            self.cache_hit_tokens += hit
            miss = _as_int(usage.get("cache_miss_tokens"))
            self.cache_miss_tokens += miss if miss is not None else max(prompt - hit, 0)

        model = (response.model or "").strip()
        if model and model not in self.models:
            self.models.append(model)

    def to_dict(self) -> dict[str, Any]:
        seconds = round(self.llm_seconds, 3)
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            "cache_reported": self.cache_reported,
            "llm_seconds": seconds,
            "tokens_per_second": (
                round(self.completion_tokens / self.llm_seconds, 2) if self.llm_seconds > 0 else 0.0
            ),
            "models": list(self.models),
        }


_collector: ContextVar[UsageCollector | None] = ContextVar("llm_usage_collector", default=None)


@contextmanager
def collect_usage() -> Iterator[UsageCollector]:
    """开启一个用量作用域：块内的 LLM 调用都累计到同一个 collector。"""
    collector = UsageCollector()
    token = _collector.set(collector)
    try:
        yield collector
    finally:
        _collector.reset(token)


def current_collector() -> UsageCollector | None:
    return _collector.get()


def record_usage(response: LLMResponse, elapsed_seconds: float) -> None:
    """记录一次调用；无作用域时静默忽略（例如单次问答接口）。"""
    collector = _collector.get()
    if collector is not None:
        collector.record(response, elapsed_seconds)


class UsageTrackingProvider(LLMProvider):
    """给任意 Provider 包一层用量统计（``chat_structured`` 内部也走 ``chat``）。"""

    name = "usage_tracking"

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner

    @property
    def inner(self) -> LLMProvider:
        return self._inner

    @property
    def is_local(self) -> bool:
        """透传底层 Provider 的本地标记（记忆预算据此收紧）。"""
        return bool(getattr(self._inner, "is_local", False))

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        started = time.perf_counter()
        response = await self._inner.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        record_usage(response, time.perf_counter() - started)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()
