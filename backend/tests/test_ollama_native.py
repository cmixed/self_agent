"""Ollama 原生协议 Provider：关闭思考、协议差异、错误分类、工厂装配。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.llm.base import (
    ChatMessage,
    LLMLocalInferenceError,
    LLMLocalServiceUnavailableError,
)
from app.llm.factory import _build_provider, provider_configs
from app.llm.ollama_native import OllamaNativeProvider, native_root
from app.llm.provider_config import ProviderConfig


def native_body(content: str = "正文", thinking: str = "", done_reason: str = "stop") -> dict:
    return {
        "model": "qwen3:4b",
        "message": {"role": "assistant", "content": content, "thinking": thinking},
        "done": True,
        "done_reason": done_reason,
        "eval_count": 120,
        "eval_duration": 2_000_000_000,  # 2s
        "prompt_eval_count": 30,
    }


def make_native(handler, **kwargs) -> OllamaNativeProvider:
    kwargs.setdefault("base_url", "http://127.0.0.1:11434/v1")
    kwargs.setdefault("model", "qwen3:4b")
    kwargs.setdefault("max_retries", 0)
    return OllamaNativeProvider(transport=httpx.MockTransport(handler), **kwargs)


def test_native_root_strips_openai_suffix() -> None:
    assert native_root("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434"
    assert native_root("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    assert native_root("http://127.0.0.1:11434/api") == "http://127.0.0.1:11434"
    assert native_root("http://box:11434") == "http://box:11434"


async def test_thinking_disabled_by_default_uses_native_path() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.read())
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=native_body("RAG 是检索增强生成。"))

    provider = make_native(handler)
    try:
        response = await provider.chat([ChatMessage(role="user", content="hi")])
        assert captured["path"] == "/api/chat", "本地 Ollama 应走原生接口"
        assert captured["body"]["think"] is False, "默认应关闭思考"
        assert captured["body"]["stream"] is False
        assert captured["auth"] is None, "本地服务不发 Authorization"
        assert response.content == "RAG 是检索增强生成。"
    finally:
        await provider.aclose()


async def test_thinking_enabled_omits_think_field() -> None:
    """要求保留思考时不传 think（沿用服务端默认），避免非思考模型报错。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        assert "think" not in body
        return httpx.Response(200, json=native_body("ok"))

    provider = make_native(handler, think=True)
    try:
        assert (await provider.chat([ChatMessage(role="user", content="hi")])).content == "ok"
    finally:
        await provider.aclose()


async def test_json_mode_uses_format_field() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.read()))
        return httpx.Response(200, json=native_body('{"goal": "ok"}'))

    provider = make_native(handler)
    try:
        await provider.chat([ChatMessage(role="user", content="规划")], json_mode=True)
        assert seen[-1]["format"] == "json"
        assert "response_format" not in seen[-1]
    finally:
        await provider.aclose()


async def test_generation_options_map_to_native_fields() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.read()))
        return httpx.Response(200, json=native_body())

    provider = make_native(handler)
    try:
        await provider.chat(
            [ChatMessage(role="user", content="hi")], temperature=0.2, max_tokens=64
        )
        options = seen[-1]["options"]
        assert options["temperature"] == 0.2
        assert options["num_predict"] == 64
    finally:
        await provider.aclose()


async def test_finish_reason_maps_length() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=native_body("半截", done_reason="length"))

    provider = make_native(handler)
    try:
        response = await provider.chat([ChatMessage(role="user", content="hi")])
        # 截断信号必须保留：writer 依赖它决定是否续写（§15）
        assert response.finish_reason == "length"
    finally:
        await provider.aclose()


async def test_thinking_only_response_yields_empty_content() -> None:
    """思考内容不并入正文（§17 不展示 CoT）；正文为空时如实返回空串。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=native_body("", thinking="一大段思考"))

    provider = make_native(handler)
    try:
        response = await provider.chat([ChatMessage(role="user", content="hi")])
        assert response.content == ""
    finally:
        await provider.aclose()


async def test_unreachable_local_service_raises_actionable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = make_native(handler)
    try:
        with pytest.raises(LLMLocalServiceUnavailableError):
            await provider.chat([ChatMessage(role="user", content="hi")])
    finally:
        await provider.aclose()


async def test_local_5xx_raises_inference_error_without_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"error": "context length exceeded"})

    provider = make_native(handler, max_retries=2)
    try:
        with pytest.raises(LLMLocalInferenceError):
            await provider.chat([ChatMessage(role="user", content="hi")])
        assert len(calls) == 1
    finally:
        await provider.aclose()


# --- 工厂装配 ---


def test_factory_builds_native_provider_for_ollama_flavor() -> None:
    provider = _build_provider(
        ProviderConfig(
            id="custom-x",
            label="Ollama（本地）",
            base_url="http://127.0.0.1:11434/v1",
            model="qwen3:4b",
            requires_api_key=False,
            is_local=True,
            flavor="ollama",
            disable_thinking=True,
        )
    )
    assert isinstance(provider, OllamaNativeProvider)
    assert provider._think is False  # noqa: SLF001 - 断言组装结果


def test_factory_keeps_openai_provider_for_openai_flavor() -> None:
    from app.llm.custom import CustomProvider

    provider = _build_provider(
        ProviderConfig(
            id="custom-y",
            label="Kimi",
            base_url="https://api.moonshot.cn/v1",
            model="kimi-k3",
            api_key="sk-x",
            flavor="openai",
        )
    )
    assert isinstance(provider, CustomProvider)
    assert not isinstance(provider, OllamaNativeProvider)


def test_ollama_flavor_keeps_thinking_by_default() -> None:
    """未要求关闭思考时不应传 think（沿用模型默认）。"""
    provider = _build_provider(
        ProviderConfig(
            id="ollama",
            label="Ollama（本地）",
            base_url="http://127.0.0.1:11434/v1",
            model="qwen3:4b",
            requires_api_key=False,
            is_local=True,
            flavor="ollama",
            disable_thinking=False,
        )
    )
    assert isinstance(provider, OllamaNativeProvider)
    assert provider._think is True  # noqa: SLF001
    assert provider_configs  # 保持导入使用


async def test_think_field_rejection_falls_back_without_it() -> None:
    """模型不接受 think 参数时，去掉该字段重试一次（不占重试预算）。"""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        seen.append(body)
        if "think" in body:
            return httpx.Response(
                400, json={"error": "this model does not support thinking"}
            )
        return httpx.Response(200, json=native_body("普通模型的正文"))

    provider = make_native(handler, max_retries=0)
    try:
        response = await provider.chat([ChatMessage(role="user", content="hi")])
        assert response.content == "普通模型的正文"
        assert len(seen) == 2, "应恰好回退一次"
        assert "think" not in seen[-1]
    finally:
        await provider.aclose()
