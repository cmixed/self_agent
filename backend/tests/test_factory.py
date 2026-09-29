from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.llm.base import LLMConfigError
from app.llm.deepseek import DeepSeekProvider
from app.llm.factory import close_llm, get_llm, reset_llm


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
