from __future__ import annotations

from app.core.config import Settings


def test_cors_origin_list_splits_and_strips() -> None:
    settings = Settings(_env_file=None, cors_origins="http://a:5173, http://b:5173 ,")
    assert settings.cors_origin_list == ["http://a:5173", "http://b:5173"]


def test_llm_configured_false_without_key(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.llm_configured is False


def test_llm_configured_true_with_key() -> None:
    settings = Settings(_env_file=None, deepseek_api_key="secret")
    assert settings.llm_configured is True


def test_default_model_is_deepseek_flash() -> None:
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "deepseek"
    assert settings.deepseek_model == "deepseek-flash"
