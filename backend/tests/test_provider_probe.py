"""模型发现与连通性测试（后端代理）。"""

from __future__ import annotations

import json

import httpx

from app.llm.probe import list_remote_models, probe_chat


def models_handler(items: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"object": "list", "data": [{"id": i} for i in items]})

    return handler


async def test_list_models_returns_sorted_ids() -> None:
    result = await list_remote_models(
        base_url="http://127.0.0.1:11434/v1",
        transport=httpx.MockTransport(models_handler(["qwen3:4b", "llama3.2:3b"])),
    )
    assert result.ok is True
    assert result.models == ["llama3.2:3b", "qwen3:4b"]


async def test_list_models_reports_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = await list_remote_models(
        base_url="http://127.0.0.1:11434/v1", transport=httpx.MockTransport(handler)
    )
    assert result.ok is False
    assert "无法连接" in result.detail
    assert "11434" in result.detail


async def test_list_models_requires_base_url() -> None:
    result = await list_remote_models(base_url="  ")
    assert result.ok is False
    assert "Base URL" in result.detail


async def test_list_models_rejects_non_openai_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": ["x"]})  # 非 OpenAI 兼容格式

    result = await list_remote_models(
        base_url="http://127.0.0.1:11434/v1", transport=httpx.MockTransport(handler)
    )
    assert result.ok is False
    assert "OpenAI 兼容" in result.detail


async def test_probe_chat_success_and_auth_header() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 2},
            },
        )

    result = await probe_chat(
        base_url="https://api.moonshot.cn/v1",
        model="kimi-k3",
        api_key="secret-key",
        transport=httpx.MockTransport(handler),
    )
    assert result.ok is True
    assert result.reply == "pong"
    assert captured["auth"] == "Bearer secret-key"
    assert "kimi-k3" in captured["body"]


async def test_probe_chat_local_needs_no_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") is None
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 1},
            },
        )

    result = await probe_chat(
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3:4b",
        requires_api_key=False,
        is_local=True,
        transport=httpx.MockTransport(handler),
    )
    assert result.ok is True


async def test_probe_chat_local_unavailable_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = await probe_chat(
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3:4b",
        requires_api_key=False,
        is_local=True,
        transport=httpx.MockTransport(handler),
    )
    assert result.ok is False
    assert "无法连接" in result.detail


async def test_probe_chat_requires_model_and_url() -> None:
    assert (await probe_chat(base_url="", model="m")).ok is False
    assert (await probe_chat(base_url="http://x/v1", model=" ")).ok is False


# --- API ---


def test_probe_and_models_endpoints() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        bad = client.get("/api/providers/models", params={"base_url": "ftp://x"})
        assert bad.status_code == 400
        assert bad.json()["error_type"] == "invalid_base_url"

        # 未运行的本地端口：应返回可读原因而不是异常
        failed = client.get(
            "/api/providers/models", params={"base_url": "http://127.0.0.1:59999/v1"}
        )
        assert failed.status_code == 200
        assert failed.json()["ok"] is False
        assert failed.json()["detail"]

        tested = client.post(
            "/api/providers/test",
            json={"base_url": "http://127.0.0.1:59999/v1", "model": "m", "is_local": True,
                  "requires_api_key": False, "timeout_seconds": 2},
        )
        assert tested.status_code == 200
        body = tested.json()
        assert body["ok"] is False
        assert "无法连接" in body["detail"]


# --- 本地服务不可用：错误类型与任务路径 ---


async def test_connect_error_on_local_provider_raises_local_unavailable() -> None:
    import pytest

    from app.llm.base import ChatMessage, LLMLocalServiceUnavailableError
    from app.llm.custom import CustomProvider

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = CustomProvider(
        provider_id="ollama",
        label="Ollama（本地）",
        api_key="",
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3:4b",
        requires_api_key=False,
        is_local=True,
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(LLMLocalServiceUnavailableError):
            await provider.chat([ChatMessage(role="user", content="hi")])
    finally:
        await provider.aclose()


async def test_connect_error_on_remote_provider_is_generic_upstream() -> None:
    """远端服务连不上仍是通用上游异常（不应误报"本地服务未启动"）。"""
    import pytest

    from app.llm.base import ChatMessage, LLMLocalServiceUnavailableError, LLMUpstreamError
    from app.llm.custom import CustomProvider

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = CustomProvider(
        provider_id="kimi",
        label="Kimi",
        api_key="k",
        base_url="https://api.moonshot.cn/v1",
        model="kimi-k3",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(LLMUpstreamError) as exc_info:
            await provider.chat([ChatMessage(role="user", content="hi")])
        assert not isinstance(exc_info.value, LLMLocalServiceUnavailableError)
    finally:
        await provider.aclose()


def test_local_unavailable_maps_to_actionable_message() -> None:
    from app.core.errors import error_type_of, resolve_error
    from app.llm.base import LLMLocalServiceUnavailableError

    status_code, detail = resolve_error(LLMLocalServiceUnavailableError("x"))
    assert status_code == 503
    assert "本地模型服务未启动" in detail
    assert "Ollama" in detail
    assert error_type_of(LLMLocalServiceUnavailableError("x")) == "llm_local_unavailable"


async def test_task_failed_event_reports_local_unavailable(tmp_path) -> None:
    """本地服务未启动时，任务应以可操作文案失败，而不是笼统的上游异常。"""
    from app.llm.base import LLMLocalServiceUnavailableError, LLMProvider
    from app.services.task_service import TaskService

    class DeadLocalProvider(LLMProvider):
        name = "ollama"
        display_name = "Ollama（本地）"

        async def chat(self, messages, *, temperature=0.7, max_tokens=None, json_mode=False):
            raise LLMLocalServiceUnavailableError("connection refused")

        async def aclose(self) -> None:
            return None

    events = [
        event
        async for event in TaskService(DeadLocalProvider(), max_retries=0).stream("写点东西")
    ]
    failed = events[-1]
    assert failed["event"] == "task_failed"
    assert failed["status"] == "error"
    assert failed["error_type"] == "llm_local_unavailable"
    assert "本地模型服务未启动" in failed["message"]


async def test_probe_reports_thinking_only_reply() -> None:
    """思考型模型（qwen3 等）可能只输出思考内容：连接成功但要如实说明。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"total_tokens": 32},
            },
        )

    result = await probe_chat(
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3:4b",
        requires_api_key=False,
        is_local=True,
        transport=httpx.MockTransport(handler),
    )
    assert result.ok is True
    assert result.reply == ""
    assert "思考内容" in result.detail


async def test_probe_requests_enough_tokens_for_thinking_models() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}]},
        )

    provider_result = await probe_chat(
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3:4b",
        requires_api_key=False,
        is_local=True,
        transport=httpx.MockTransport(handler),
    )
    assert provider_result.ok is True
    assert seen[-1]["max_tokens"] >= 32, "预算过小会被思考过程吃光，拿不到正文"
