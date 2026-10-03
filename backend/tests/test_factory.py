from __future__ import annotations

import json

import pytest

from app.core.config import get_settings
from app.core.provider_store import ProviderStore
from app.llm.base import LLMConfigError
from app.llm.deepseek import DeepSeekProvider
from app.llm.factory import (
    close_llm,
    current_llm_provider,
    get_llm,
    reset_llm,
    switch_llm_provider,
)
from app.llm.glm import GLMProvider


@pytest.fixture(autouse=True)
def _reset_provider():
    reset_llm()
    yield
    reset_llm()


async def test_get_llm_returns_deepseek_and_is_cached(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    get_settings.cache_clear()

    provider = get_llm()
    try:
        assert isinstance(provider, DeepSeekProvider)
        assert get_llm() is provider
    finally:
        await close_llm()


async def test_unknown_provider_raises_config_error(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    get_settings.cache_clear()

    with pytest.raises(LLMConfigError):
        get_llm()


async def test_missing_api_key_raises_config_error(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    get_settings.cache_clear()

    with pytest.raises(LLMConfigError):
        get_llm()


async def test_get_llm_returns_glm_provider(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "glm")
    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    get_settings.cache_clear()

    provider = get_llm()
    try:
        assert isinstance(provider, GLMProvider)
        assert provider.name == "glm"
    finally:
        await close_llm()


async def test_glm_without_key_raises_config_error(monkeypatch) -> None:
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "glm")
    get_settings.cache_clear()

    with pytest.raises(LLMConfigError):
        get_llm()


async def test_current_provider_prefers_persisted_choice(monkeypatch) -> None:
    """持久化选择优先于环境默认值（前提：目标 Provider 已配置密钥）。"""
    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    get_settings.cache_clear()
    ProviderStore(get_settings().settings_path).save("glm")
    reset_llm()

    assert current_llm_provider() == "glm"
    assert isinstance(get_llm(), GLMProvider)


async def test_switch_llm_provider_swaps_closes_old_and_persists(monkeypatch) -> None:
    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    get_settings.cache_clear()

    old_provider = get_llm()
    assert isinstance(old_provider, DeepSeekProvider)
    closed = {"flag": False}

    async def _spy_aclose() -> None:
        closed["flag"] = True

    monkeypatch.setattr(old_provider, "aclose", _spy_aclose)

    result = await switch_llm_provider("glm")

    assert result == "glm"
    assert closed["flag"] is True
    assert isinstance(get_llm(), GLMProvider)
    assert current_llm_provider() == "glm"
    store_path = get_settings().settings_path
    assert json.loads(store_path.read_text(encoding="utf-8"))["llm_provider"] == "glm"


async def test_switch_to_unconfigured_provider_keeps_current(monkeypatch) -> None:
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    get_settings.cache_clear()

    old_provider = get_llm()

    with pytest.raises(LLMConfigError) as exc_info:
        await switch_llm_provider("glm")

    assert "GLM_API_KEY" in str(exc_info.value)
    assert get_llm() is old_provider


async def test_switch_to_same_provider_is_noop() -> None:
    current = get_llm()
    result = await switch_llm_provider("deepseek")

    assert result == "deepseek"
    assert get_llm() is current
