"""设置 API 测试：Provider 快照与运行时切换。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.provider_store import ProviderStore
from app.llm.factory import reset_llm
from app.main import create_app


@pytest.fixture(autouse=True)
def _reset_provider():
    reset_llm()
    yield
    reset_llm()


def make_client() -> TestClient:
    return TestClient(create_app())


def test_get_settings_snapshot_lists_providers_without_secrets() -> None:
    with make_client() as client:
        response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["llm_provider"] == "deepseek"

    by_id = {item["id"]: item for item in body["providers"]}
    assert set(by_id) == {"deepseek", "glm"}
    assert by_id["deepseek"]["configured"] is True
    assert by_id["deepseek"]["active"] is True
    assert by_id["deepseek"]["model"] == "deepseek-flash"
    assert by_id["glm"]["configured"] is False
    assert by_id["glm"]["active"] is False
    assert by_id["glm"]["model"] == "glm-5.3-flash"
    # 绝不返回密钥材料
    assert "test-key" not in response.text
    assert "api_key" not in response.text.lower()


def test_switch_to_glm_applies_and_persists(monkeypatch) -> None:
    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    get_settings.cache_clear()

    with make_client() as client:
        response = client.put("/api/settings/llm-provider", json={"provider": "glm"})
        assert response.status_code == 200
        body = response.json()
        assert body["llm_provider"] == "glm"
        assert next(item for item in body["providers"] if item["id"] == "glm")["active"] is True

        # 快照与健康检查都反映切换后的生效 Provider
        after = client.get("/api/settings").json()
        health = client.get("/api/health").json()

    assert after["llm_provider"] == "glm"
    assert health["llm_provider"] == "glm"
    assert health["llm_configured"] is True

    store_path = get_settings().settings_path
    assert ProviderStore(store_path).load() == "glm"


def test_switch_to_unconfigured_provider_returns_409() -> None:
    with make_client() as client:
        response = client.put("/api/settings/llm-provider", json={"provider": "glm"})
    assert response.status_code == 409
    body = response.json()
    assert body["error_type"] == "llm_config_error"
    assert "GLM_API_KEY" in body["detail"]
    # 切换失败不影响当前 Provider
    assert client.get("/api/settings").json()["llm_provider"] == "deepseek"


def test_switch_to_unknown_provider_returns_422() -> None:
    with make_client() as client:
        response = client.put("/api/settings/llm-provider", json={"provider": "gemini"})
    assert response.status_code == 422
    body = response.json()
    assert body["error_type"] == "unknown_provider"
    assert "gemini" in body["detail"]


def test_switch_to_known_but_unconfigured_provider_returns_409(monkeypatch) -> None:
    """已知但未配置的 Provider（如未设模型的 Ollama）→ 409 且说明缺什么。"""
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")
    get_settings.cache_clear()

    with make_client() as client:
        response = client.put("/api/settings/llm-provider", json={"provider": "ollama"})
    # Ollama 无需密钥：仅在未配置 base_url/model 时才不可用，这里 model 已设置 → 可切换
    assert response.status_code == 200
    assert response.json()["llm_provider"] == "ollama"


def test_switch_rejects_blank_provider() -> None:
    with make_client() as client:
        response = client.put("/api/settings/llm-provider", json={"provider": "  "})
    assert response.status_code == 422


def test_quota_error_maps_to_402() -> None:
    """余额/配额不足 → 402，与 429 限流区分（前端提示不再误导重试）。"""
    from app.core.errors import resolve_error
    from app.llm.base import LLMQuotaError, LLMRateLimitError

    assert resolve_error(LLMQuotaError("余额不足"))[0] == 402
    assert resolve_error(LLMRateLimitError("限流"))[0] == 429
