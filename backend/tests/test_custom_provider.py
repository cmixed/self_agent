"""自定义 / 本地 OpenAI 兼容 Provider：无密钥、response_format 回退、配置装配。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.llm.base import (
    ChatMessage,
    LLMConfigError,
    LLMLocalInferenceError,
    LLMUpstreamError,
)
from app.llm.custom import CustomProvider
from app.llm.factory import (
    ProviderConfig,
    _build_provider,
    provider_configs,
    reset_llm,
)

KIMI_BASE = "https://api.moonshot.cn/v1"


def make_provider(handler, **kwargs) -> CustomProvider:
    kwargs.setdefault("max_retries", 2)
    return CustomProvider(
        provider_id=kwargs.pop("provider_id", "custom"),
        label=kwargs.pop("label", "自定义接口"),
        api_key=kwargs.pop("api_key", "test-key"),
        base_url=kwargs.pop("base_url", KIMI_BASE),
        model=kwargs.pop("model", "kimi-k3"),
        transport=httpx.MockTransport(handler),
        retry_backoff_seconds=0.0,
        **kwargs,
    )


def success_body(content: str = "hi") -> dict:
    return {
        "model": "kimi-k3",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 3},
    }


# --- 无密钥（本地服务）---


async def test_local_provider_needs_no_api_key() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["path"] = request.url.path
        return httpx.Response(200, json=success_body("本地模型回答"))

    provider = make_provider(
        handler, api_key="", requires_api_key=False, is_local=True, base_url="http://127.0.0.1:11434/v1"
    )
    try:
        response = await provider.chat([ChatMessage(role="user", content="你好")])
        assert response.content == "本地模型回答"
        assert captured["auth"] is None  # 不发 Authorization
        assert captured["path"].endswith("/chat/completions")
        assert provider.is_local is True
    finally:
        await provider.aclose()


async def test_remote_provider_still_requires_key() -> None:
    with pytest.raises(LLMConfigError):
        CustomProvider(
            provider_id="custom",
            label="x",
            api_key="   ",
            base_url=KIMI_BASE,
            model="kimi-k3",
        )


# --- response_format 兼容回退 ---


async def test_falls_back_when_endpoint_rejects_response_format() -> None:
    """端点不支持 response_format（400）时去掉该参数重试，而不是让整单任务失败。"""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        seen.append(payload)
        if "response_format" in payload:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported parameter: response_format",
                        "type": "invalid_request_error",
                    }
                },
            )
        return httpx.Response(200, json=success_body('{"goal": "ok"}'))

    provider = make_provider(handler)
    try:
        response = await provider.chat(
            [ChatMessage(role="user", content="规划")], json_mode=True
        )
        assert "response_format" not in seen[-1]
        assert json.loads(response.content)["goal"] == "ok"
        # 探测结果被记住：后续调用不再先撞一次 400
        before = len(seen)
        await provider.chat([ChatMessage(role="user", content="再规划")], json_mode=True)
        assert len(seen) == before + 1
        assert "response_format" not in seen[-1]
    finally:
        await provider.aclose()


async def test_other_400_is_not_treated_as_json_fallback() -> None:
    """与 response_format 无关的 400 不能触发回退（否则掩盖真实错误）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "model not found"}})

    provider = make_provider(handler)
    try:
        with pytest.raises(Exception) as exc_info:
            await provider.chat([ChatMessage(role="user", content="hi")], json_mode=True)
        assert "model not found" in str(exc_info.value)
    finally:
        await provider.aclose()


async def test_supported_response_format_is_sent_normally() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.read()))
        return httpx.Response(200, json=success_body('{"ok": true}'))

    provider = make_provider(handler)
    try:
        await provider.chat([ChatMessage(role="user", content="规划")], json_mode=True)
        assert seen[-1]["response_format"] == {"type": "json_object"}
    finally:
        await provider.aclose()


# --- 配置装配（Kimi 走自定义端点）---


def test_kimi_config_builds_custom_provider(monkeypatch) -> None:
    monkeypatch.setenv("CUSTOM_BASE_URL", KIMI_BASE)
    monkeypatch.setenv("CUSTOM_MODEL", "kimi-k3")
    monkeypatch.setenv("CUSTOM_API_KEY", "moonshot-test-key")
    monkeypatch.setenv("CUSTOM_LABEL", "Kimi")
    get_settings.cache_clear()

    configs = provider_configs(get_settings())
    assert {"deepseek", "glm", "custom"} <= set(configs)
    custom = configs["custom"]
    assert custom.label == "Kimi"
    assert custom.base_url == KIMI_BASE
    assert custom.model == "kimi-k3"
    assert custom.available is True

    provider = _build_provider(custom)
    assert provider.name == "custom"
    assert provider.display_name == "Kimi"
    reset_llm()


def test_unconfigured_optional_providers_are_hidden() -> None:
    """未配置的可选 Provider（自定义端点 / Ollama）不列出。

    切换器只应出现真正可用的服务；未配置的灰项容易被误解为"坏了"，
    发现入口统一放在「模型服务」页。
    """
    settings = Settings(_env_file=None)
    configs = provider_configs(settings)
    assert "custom" not in configs
    assert "ollama" not in configs


def test_ollama_listed_once_model_configured(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")
    get_settings.cache_clear()
    config = provider_configs(get_settings())["ollama"]
    assert config.is_local is True
    assert config.requires_api_key is False
    assert config.available is True
    assert config.api_key_env == "OLLAMA_MODEL"  # 错误提示指向模型名而非密钥
    reset_llm()


def test_local_custom_provider_available_without_key(monkeypatch) -> None:
    monkeypatch.setenv("CUSTOM_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setenv("CUSTOM_MODEL", "local-model")
    monkeypatch.setenv("CUSTOM_REQUIRES_API_KEY", "false")
    monkeypatch.setenv("CUSTOM_IS_LOCAL", "true")
    get_settings.cache_clear()

    custom = provider_configs(get_settings())["custom"]
    assert custom.available is True
    assert custom.is_local is True
    assert custom.requires_api_key is False
    reset_llm()


def test_provider_config_available_rules() -> None:
    assert ProviderConfig(id="x", label="X", base_url="", model="m", api_key="k").available is False
    assert ProviderConfig(id="x", label="X", base_url="u", model="", api_key="k").available is False
    assert ProviderConfig(id="x", label="X", base_url="u", model="m", api_key="").available is False
    assert (
        ProviderConfig(id="x", label="X", base_url="u", model="m", api_key="k").available is True
    )
    assert (
        ProviderConfig(
            id="x", label="X", base_url="u", model="m", requires_api_key=False
        ).available
        is True
    )


async def test_planner_tolerates_missing_needs_retrieval(monkeypatch) -> None:
    """本地小模型常省略 needs_retrieval：应按「需要检索」处理而不是整单失败。"""
    import httpx as _httpx

    from app.agents.planner import PlanModel, make_planner_node
    from app.models.state import initial_state

    payload = {
        "model": "local",
        "choices": [
            {
                "message": {
                    "content": '{"goal": "写综述", "steps": ['
                    '{"id": "write", "type": "writing", "description": "写正文"}]}'
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"total_tokens": 5},
    }

    def handler(request: _httpx.Request) -> _httpx.Response:
        return _httpx.Response(200, json=payload)

    provider = make_provider(
        handler, api_key="", requires_api_key=False, is_local=True,
        base_url="http://127.0.0.1:11434/v1",
    )
    try:
        node = make_planner_node(provider)
        update = await node(initial_state("写综述", task_id="t"))
        assert update["plan"]["needs_retrieval"] is True
    finally:
        await provider.aclose()

    # 缺省值语义直接断言（避免只靠集成路径）
    model = PlanModel.model_validate(
        {"goal": "g", "steps": [{"id": "s", "type": "writing", "description": "d"}]}
    )
    assert model.needs_retrieval is True


# --- 本地推理失败（5xx）：单独建模并给出可操作提示 ---


async def test_local_5xx_raises_actionable_error_without_retry() -> None:
    """本地 5xx 多为上下文/显存问题：立即抛出（重试无用），并映射为可操作文案。"""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"error": "context length exceeded"})

    provider = make_provider(
        handler, api_key="", requires_api_key=False, is_local=True,
        base_url="http://127.0.0.1:11434/v1", max_retries=2,
    )
    try:
        with pytest.raises(LLMLocalInferenceError):
            await provider.chat([ChatMessage(role="user", content="hi")])
        assert len(calls) == 1, "本地推理失败不应浪费重试预算"
    finally:
        await provider.aclose()


async def test_remote_5xx_stays_generic_upstream_error() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"error": "internal"})

    provider = make_provider(handler, max_retries=1)
    try:
        with pytest.raises(LLMUpstreamError) as exc_info:
            await provider.chat([ChatMessage(role="user", content="hi")])
        assert not isinstance(exc_info.value, LLMLocalInferenceError)
        assert len(calls) == 2, "云端 5xx 仍按配置重试"
    finally:
        await provider.aclose()


def test_local_inference_error_maps_to_context_hint() -> None:
    from app.core.errors import error_type_of, resolve_error
    from app.llm.base import LLMLocalInferenceError

    status_code, detail = resolve_error(LLMLocalInferenceError("boom"))
    assert status_code == 502
    assert "OLLAMA_CONTEXT_LENGTH" in detail
    assert "显存" in detail
    assert error_type_of(LLMLocalInferenceError("x")) == "llm_local_inference_failed"
