from __future__ import annotations

from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm_provider
from app.llm.base import (
    ChatMessage,
    LLMConfigError,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
)


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, *, content: str = "这是一个测试回答", error: LLMError | None = None) -> None:
        self.content = content
        self.error = error
        self.received: list[ChatMessage] = []
        self.closed = False

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        self.received = list(messages)
        if self.error is not None:
            raise self.error
        return LLMResponse(content=self.content, model="fake-model", usage={"total_tokens": 7})

    async def aclose(self) -> None:
        self.closed = True


def make_client(provider: FakeProvider) -> TestClient:
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_llm_provider] = lambda: provider
    return TestClient(app)


def test_health_ok() -> None:
    with make_client(FakeProvider()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_provider"] == "deepseek"
    assert "deepseek_api_key" not in response.text


def test_chat_returns_answer_from_provider() -> None:
    provider = FakeProvider(content="你好，我是 Agent")
    with make_client(provider) as client:
        response = client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "你好"}]}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "你好，我是 Agent"
    assert body["model"] == "fake-model"
    assert body["usage"] == {"total_tokens": 7}
    assert provider.received[0].content == "你好"


def test_chat_rejects_empty_messages() -> None:
    with make_client(FakeProvider()) as client:
        response = client.post("/api/chat", json={"messages": []})
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (LLMConfigError("未配置"), 503),
        (LLMRateLimitError("限流"), 429),
    ],
)
def test_chat_maps_llm_errors_to_http_status(error: LLMError, expected_status: int) -> None:
    with make_client(FakeProvider(error=error)) as client:
        response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == expected_status


def test_chat_returns_503_when_provider_dependency_fails() -> None:
    """配置错误在依赖解析阶段抛出时，也必须被统一映射，而不是 500。"""
    from app.main import create_app

    app = create_app()

    def _raise() -> LLMProvider:
        raise LLMConfigError("DEEPSEEK_API_KEY 未配置")

    app.dependency_overrides[get_llm_provider] = _raise
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 503
    assert response.json()["error_type"] == "llm_config_error"


def test_chat_error_response_is_sanitized() -> None:
    provider = FakeProvider(error=LLMConfigError("DEEPSEEK_API_KEY=super-secret"))
    with make_client(provider) as client:
        response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert "super-secret" not in response.text
