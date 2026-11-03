"""LLM 用量采集：token / 缓存命中 / 速度。

覆盖点：
- 上游两种缓存字段（DeepSeek 顶层、OpenAI/GLM 嵌套）都能归一化；
- 装饰器 + ContextVar 在并发任务间互不串扰；
- Agent 任务完成后，用量进入 ``service.last_usage`` 与结果结构（落库/SSE 同源）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from fakes import OUTLINE_JSON, PLAN_JSON, ScriptedProvider
from fastapi.testclient import TestClient

from app.llm.base import ChatMessage, LLMProvider, LLMResponse
from app.llm.usage import (
    UsageCollector,
    UsageTrackingProvider,
    collect_usage,
    parse_usage,
)
from app.main import create_app
from app.models.schemas import TaskResponse
from app.services.task_service import TaskService, task_result


class StaticUsageProvider(LLMProvider):
    """固定返回一份 usage 的假 Provider（用于验证累加与并发隔离）。"""

    name = "static-usage"

    def __init__(self, *, prompt: int = 10, completion: int = 5, model: str = "fake-1") -> None:
        self._prompt = prompt
        self._completion = completion
        self._model = model

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        return LLMResponse(
            content="ok",
            model=self._model,
            usage={
                "prompt_tokens": self._prompt,
                "completion_tokens": self._completion,
                "total_tokens": self._prompt + self._completion,
            },
        )

    async def aclose(self) -> None:
        return None


class UsageScriptedProvider(ScriptedProvider):
    """在脚本化 Provider 上带一份可预期的 usage（含缓存命中）。"""

    async def chat(self, *args, **kwargs) -> LLMResponse:
        response = await super().chat(*args, **kwargs)
        return response.model_copy(
            update={
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "cache_hit_tokens": 40,
                    "cache_miss_tokens": 60,
                }
            }
        )


# --- parse_usage ---


def test_parse_usage_flattens_openai_cached_tokens() -> None:
    usage = parse_usage(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {"cached_tokens": 8},
        }
    )

    assert usage["total_tokens"] == 15
    assert usage["cache_hit_tokens"] == 8


def test_parse_usage_understands_deepseek_cache_fields() -> None:
    usage = parse_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 70,
            "prompt_cache_miss_tokens": 30,
        }
    )

    assert usage["cache_hit_tokens"] == 70
    assert usage["cache_miss_tokens"] == 30
    # 上游原始键保留，/api/chat 的返回结构不变
    assert usage["prompt_cache_hit_tokens"] == 70


def test_parse_usage_ignores_non_integer_values() -> None:
    usage = parse_usage({"prompt_tokens": 3, "note": "x", "flag": True})

    assert usage == {"prompt_tokens": 3}


# --- collector ---


def test_collector_accumulates_and_computes_speed() -> None:
    collector = UsageCollector()
    collector.record(
        LLMResponse(
            content="",
            model="m",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "cache_hit_tokens": 60,
                "cache_miss_tokens": 40,
            },
        ),
        elapsed_seconds=2.0,
    )
    collector.record(
        LLMResponse(
            content="",
            model="m",
            usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        ),
        elapsed_seconds=1.0,
    )

    snapshot = collector.to_dict()

    assert snapshot["calls"] == 2
    assert snapshot["prompt_tokens"] == 150
    assert snapshot["completion_tokens"] == 60
    assert snapshot["total_tokens"] == 210
    assert snapshot["cache_hit_tokens"] == 60
    assert snapshot["cache_miss_tokens"] == 40
    assert snapshot["llm_seconds"] == 3.0
    assert snapshot["tokens_per_second"] == 20.0
    assert snapshot["models"] == ["m"]


def test_collector_marks_cache_as_unreported_when_absent() -> None:
    collector = UsageCollector()
    collector.record(
        LLMResponse(content="", model="local", usage={"prompt_tokens": 5, "completion_tokens": 5}),
        elapsed_seconds=0.5,
    )

    snapshot = collector.to_dict()

    assert snapshot["cache_reported"] is False
    assert snapshot["cache_hit_tokens"] == 0
    # 总量缺失时由输入 + 输出补齐
    assert snapshot["total_tokens"] == 10


async def test_concurrent_collectors_do_not_leak() -> None:
    async def run(prompt: int) -> dict:
        with collect_usage() as usage:
            provider = UsageTrackingProvider(StaticUsageProvider(prompt=prompt))
            await provider.chat([ChatMessage(role="user", content="hi")])
            await asyncio.sleep(0)
            return usage.to_dict()

    first, second = await asyncio.gather(run(3), run(7))

    assert first["prompt_tokens"] == 3
    assert second["prompt_tokens"] == 7


async def test_record_without_scope_is_noop() -> None:
    provider = UsageTrackingProvider(StaticUsageProvider())

    response = await provider.chat([ChatMessage(role="user", content="hi")])

    assert response.content == "ok"


async def test_deepseek_cache_fields_reach_collector() -> None:
    """DeepSeek 的 prompt_cache_hit_tokens 要穿过解析层进入采集器。"""
    import httpx

    from app.llm.deepseek import DeepSeekProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "deepseek-flash",
                "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "prompt_cache_hit_tokens": 80,
                    "prompt_cache_miss_tokens": 20,
                },
            },
        )

    inner = DeepSeekProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        retry_backoff_seconds=0.0,
    )
    try:
        with collect_usage() as usage:
            await UsageTrackingProvider(inner).chat([ChatMessage(role="user", content="hi")])
    finally:
        await inner.aclose()

    snapshot = usage.to_dict()

    assert snapshot["cache_reported"] is True
    assert snapshot["cache_hit_tokens"] == 80
    assert snapshot["cache_miss_tokens"] == 20
    assert snapshot["prompt_tokens"] == 100
    assert snapshot["completion_tokens"] == 20


# --- 任务集成 ---


async def test_task_run_collects_usage() -> None:
    provider = UsageScriptedProvider([PLAN_JSON, OUTLINE_JSON])
    service = TaskService(provider, max_retries=0)

    state = await service.run("写一篇 RAG 综述")

    usage = service.last_usage
    assert usage is not None
    assert usage["calls"] == len(provider.calls)
    assert usage["calls"] >= 1
    assert usage["prompt_tokens"] == 100 * usage["calls"]
    assert usage["completion_tokens"] == 20 * usage["calls"]
    assert usage["cache_reported"] is True
    assert usage["cache_hit_tokens"] == 40 * usage["calls"]
    assert usage["tokens_per_second"] > 0

    result = task_result(state, max_retries=0, usage=usage)
    parsed = TaskResponse.model_validate(result)
    assert parsed.usage is not None
    assert parsed.usage.total_tokens == 120 * usage["calls"]


async def test_stream_task_completed_carries_usage() -> None:
    service = TaskService(UsageScriptedProvider([PLAN_JSON, OUTLINE_JSON]), max_retries=0)

    events = [event async for event in service.stream("写一篇 RAG 综述")]
    completed = events[-1]

    assert completed["event"] == "task_completed"
    assert completed["result"]["usage"]["calls"] >= 1
    assert completed["result"]["usage"]["prompt_tokens"] > 0


def test_task_detail_exposes_usage() -> None:
    """详情接口从 result_json 读取用量（旧记录没有该字段时为 None）。"""
    from app.api.deps import (
        build_memory_repository,
        build_task_repository,
        get_memory_service,
        get_task_service,
    )
    from app.services.memory_service import MemoryService

    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: TaskService(
        UsageScriptedProvider([PLAN_JSON, OUTLINE_JSON]),
        repository=build_task_repository(),
        max_retries=0,
    )
    # 长期记忆不接 LLM：提取为 no-op，测试完全离线
    app.dependency_overrides[get_memory_service] = lambda: MemoryService(
        build_memory_repository(), None
    )

    with TestClient(app) as client:
        created = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})
        assert created.status_code == 200
        body = created.json()
        assert body["usage"]["calls"] >= 1

        detail = client.get(f"/api/tasks/{body['task_id']}")
        assert detail.status_code == 200
        assert detail.json()["usage"] == body["usage"]
