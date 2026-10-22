"""GLM 额外模型：同一把 GLM_API_KEY 下可切换多个模型（如 glm-5.3-flashx）。

覆盖点：
- ``GLM_EXTRA_MODELS`` 解析（去空、去重、跳过主模型）；
- 额外模型复用同一密钥与端点，且能通过设置接口切换；
- 未配置密钥时仍按「未配置」处理，切换返回 409。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.llm.factory import get_llm, provider_configs, reset_llm, switch_llm_provider
from app.llm.glm import GLMProvider
from app.main import create_app

EXTRA_ID = "glm:glm-5.3-flashx"


@pytest.fixture(autouse=True)
def _reset_provider():
    reset_llm()
    yield
    reset_llm()


def _enable(
    monkeypatch: pytest.MonkeyPatch, *, extra: str, key: str | None = "test-glm-key"
) -> None:
    if key is None:
        monkeypatch.delenv("GLM_API_KEY", raising=False)
    else:
        monkeypatch.setenv("GLM_API_KEY", key)
    monkeypatch.setenv("GLM_EXTRA_MODELS", extra)
    get_settings.cache_clear()


def test_extra_model_reuses_glm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, extra="glm-5.3-flashx")

    config = provider_configs(get_settings())[EXTRA_ID]

    assert config.model == "glm-5.3-flashx"
    # 沿用同一把密钥与同一个端点
    assert config.api_key == "test-glm-key"
    assert config.base_url == get_settings().glm_base_url
    assert config.api_key_env == "GLM_API_KEY"
    assert config.available is True


def test_extra_models_are_trimmed_deduped_and_skip_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, extra=" glm-5.3-flashx , glm-5.3-flash , glm-5.3-flashx ,")

    settings = get_settings()
    configs = provider_configs(settings)

    assert settings.glm_extra_model_list == ["glm-5.3-flashx", "glm-5.3-flash"]
    assert EXTRA_ID in configs
    # 主模型不重复生成条目
    assert "glm:glm-5.3-flash" not in configs


def test_settings_helpers_understand_extra_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, extra="glm-5.3-flashx")
    settings = get_settings()

    assert settings.provider_configured(EXTRA_ID) is True
    assert settings.provider_model(EXTRA_ID) == "glm-5.3-flashx"


async def test_factory_builds_glm_provider_for_extra_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, extra="glm-5.3-flashx")

    await switch_llm_provider(EXTRA_ID)
    provider = get_llm()

    assert isinstance(provider, GLMProvider)
    assert provider._model == "glm-5.3-flashx"


def test_settings_snapshot_and_switch_to_extra_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, extra="glm-5.3-flashx")

    with TestClient(create_app()) as client:
        snapshot = client.get("/api/settings").json()
        by_id = {item["id"]: item for item in snapshot["providers"]}
        assert by_id[EXTRA_ID]["model"] == "glm-5.3-flashx"
        assert by_id[EXTRA_ID]["configured"] is True
        assert by_id[EXTRA_ID]["active"] is False

        switched = client.put("/api/settings/llm-provider", json={"provider": EXTRA_ID})
        assert switched.status_code == 200
        assert switched.json()["llm_provider"] == EXTRA_ID

        health = client.get("/api/health").json()

    assert health["llm_provider"] == EXTRA_ID
    assert health["llm_model"] == "glm-5.3-flashx"
    assert health["llm_configured"] is True


def test_extra_model_without_key_stays_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, extra="glm-5.3-flashx", key=None)

    with TestClient(create_app()) as client:
        response = client.put("/api/settings/llm-provider", json={"provider": EXTRA_ID})

    assert response.status_code == 409
    assert "GLM_API_KEY" in response.json()["detail"]
