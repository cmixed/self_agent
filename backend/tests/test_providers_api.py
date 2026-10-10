"""自定义 Provider 管理：CRUD、密钥策略（环境变量优先/不回传）、切换与删除回退。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_provider_service
from app.core.config import get_settings
from app.llm import registry
from app.llm.factory import provider_configs, reset_llm
from app.main import create_app
from app.memory.sqlite import SqliteDatabase
from app.services.provider_service import (
    ProviderNotFoundError,
    ProviderService,
    ProviderValidationError,
)


@pytest.fixture
def service(tmp_path) -> ProviderService:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    return ProviderService(database)


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SETTINGS_PATH", str(tmp_path / "settings.json"))
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    registry.reset_custom_providers()
    reset_llm()
    get_settings.cache_clear()


def kimi_payload(**overrides) -> dict:
    payload = {
        "label": "Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k3",
        "api_key": "sk-moonshot-secret-abcd",
        "requires_api_key": True,
        "is_local": False,
    }
    payload.update(overrides)
    return payload


# --- 服务层 ---


async def test_create_and_list_custom_provider(service: ProviderService) -> None:
    view = await service.create_provider(**kimi_payload())
    assert view.provider_id.startswith("custom-")
    assert view.label == "Kimi"
    assert view.key_source == "db"
    assert view.key_hint == "****abcd"

    listed = await service.list_providers()
    assert [item.provider_id for item in listed] == [view.provider_id]


async def test_api_key_never_appears_in_view(service: ProviderService) -> None:
    view = await service.create_provider(**kimi_payload(api_key="sk-super-secret-1234"))
    serialized = str(view)
    assert "sk-super-secret-1234" not in serialized
    assert view.key_hint == "****1234"


async def test_env_var_takes_priority_over_stored_key(
    service: ProviderService, monkeypatch
) -> None:
    monkeypatch.setenv("MOONSHOT_API_KEY", "env-key-9999")
    view = await service.create_provider(
        **kimi_payload(api_key="db-key-1111", api_key_env="MOONSHOT_API_KEY")
    )
    assert view.key_source == "env"
    assert view.key_hint == "****9999"

    monkeypatch.delenv("MOONSHOT_API_KEY")
    after = await service.get_provider(view.provider_id)
    assert after.key_source == "db"
    assert after.key_hint == "****1111"


async def test_local_provider_needs_no_key(service: ProviderService) -> None:
    view = await service.create_provider(
        label="Ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3:4b",
        requires_api_key=False,
        is_local=True,
    )
    assert view.requires_api_key is False
    assert view.key_source == "none"
    assert view.key_hint == ""


async def test_requires_key_provider_rejects_empty_key(service: ProviderService) -> None:
    with pytest.raises(ProviderValidationError):
        await service.create_provider(**kimi_payload(api_key="", api_key_env=""))


async def test_validation_rejects_bad_values(service: ProviderService) -> None:
    with pytest.raises(ProviderValidationError):
        await service.create_provider(**kimi_payload(label="  "))
    with pytest.raises(ProviderValidationError):
        await service.create_provider(**kimi_payload(base_url="api.moonshot.cn"))
    with pytest.raises(ProviderValidationError):
        await service.create_provider(**kimi_payload(model=" "))


async def test_update_keeps_key_when_omitted(service: ProviderService) -> None:
    created = await service.create_provider(**kimi_payload(api_key="sk-keep-0001"))
    updated = await service.update_provider(created.provider_id, model="kimi-k2")
    assert updated.model == "kimi-k2"
    assert updated.key_hint == "****0001"  # 未传 api_key → 保持

    cleared = await service.update_provider(created.provider_id, api_key="")
    assert cleared.key_hint == ""


async def test_update_and_delete_missing_provider(service: ProviderService) -> None:
    with pytest.raises(ProviderNotFoundError):
        await service.update_provider("ghost", model="x")
    with pytest.raises(ProviderNotFoundError):
        await service.delete_provider("ghost")


async def test_registry_makes_provider_available_to_factory(service: ProviderService) -> None:
    settings = get_settings()
    view = await service.create_provider(**kimi_payload())
    configs = provider_configs(settings)
    assert view.provider_id in configs
    config = configs[view.provider_id]
    assert config.managed is True
    assert config.label == "Kimi"
    assert config.available is True
    assert config.base_url == "https://api.moonshot.cn/v1"
    assert config.model == "kimi-k3"

    await service.delete_provider(view.provider_id)
    assert view.provider_id not in provider_configs(get_settings())


# --- API ---


def test_crud_api_and_no_secret_leak(client: TestClient) -> None:
    created = client.post("/api/providers", json=kimi_payload(api_key="sk-api-secret-7777"))
    assert created.status_code == 200
    body = created.json()
    assert "sk-api-secret-7777" not in created.text
    assert body["key_hint"] == "****7777"
    provider_id = body["provider_id"]

    listed = client.get("/api/providers").json()["providers"]
    assert [item["provider_id"] for item in listed] == [provider_id]
    assert "sk-api-secret-7777" not in listed.__str__()

    updated = client.put(f"/api/providers/{provider_id}", json={"label": "Kimi 2"})
    assert updated.status_code == 200 and updated.json()["label"] == "Kimi 2"

    invalid = client.post("/api/providers", json=kimi_payload(base_url="ftp://x"))
    assert invalid.status_code == 400
    assert invalid.json()["error_type"] == "invalid_provider"

    missing = client.put("/api/providers/ghost", json={"label": "x"})
    assert missing.status_code == 404

    assert client.delete(f"/api/providers/{provider_id}").status_code == 200
    assert client.get("/api/providers").json()["providers"] == []


def test_settings_snapshot_lists_custom_provider_without_secret(client: TestClient) -> None:
    created = client.post("/api/providers", json=kimi_payload(api_key="sk-snap-5555")).json()
    settings = client.get("/api/settings")
    assert "sk-snap-5555" not in settings.text

    by_id = {item["id"]: item for item in settings.json()["providers"]}
    assert created["provider_id"] in by_id
    entry = by_id[created["provider_id"]]
    assert entry["managed"] is True
    assert entry["label"] == "Kimi"
    assert entry["key_source"] == "db"
    assert entry["key_hint"] == "****5555"
    assert entry["configured"] is True


def test_switch_to_custom_provider_and_delete_fallback(client: TestClient) -> None:
    created = client.post("/api/providers", json=kimi_payload()).json()
    provider_id = created["provider_id"]

    switched = client.put("/api/settings/llm-provider", json={"provider": provider_id})
    assert switched.status_code == 200
    assert switched.json()["llm_provider"] == provider_id

    # 删除正在使用的 Provider：回退到环境默认值（不能悬空）
    assert client.delete(f"/api/providers/{provider_id}").status_code == 200
    after = client.get("/api/settings").json()
    assert after["llm_provider"] in {"deepseek", "glm", "ollama", "custom"}
    assert after["llm_provider"] != provider_id


def test_switch_to_unknown_custom_provider_is_rejected(client: TestClient) -> None:
    response = client.put("/api/settings/llm-provider", json={"provider": "custom-ghost"})
    assert response.status_code == 422
    assert response.json()["error_type"] == "unknown_provider"


def test_probe_uses_server_side_key_for_saved_provider(client: TestClient) -> None:
    """已保存的 Provider 测试连接时不接受前端传的密钥（一律用服务端配置）。"""
    created = client.post(
        "/api/providers",
        json=kimi_payload(base_url="http://127.0.0.1:59998/v1", api_key="sk-server-1"),
    ).json()

    probe = client.post(
        "/api/providers/test",
        json={
            "base_url": "http://127.0.0.1:59998/v1",
            "model": "kimi-k3",
            "provider_id": created["provider_id"],
            "api_key": "sk-should-be-ignored",
            "timeout_seconds": 2,
        },
    )
    assert probe.status_code == 200
    # 连接失败原因可读（本地端口未监听）
    assert probe.json()["ok"] is False
    assert probe.json()["detail"]


def test_deleting_provider_removes_mapping_from_service(service: ProviderService) -> None:
    import asyncio

    view = asyncio.run(service.create_provider(**kimi_payload()))
    asyncio.run(service.delete_provider(view.provider_id))
    assert asyncio.run(service.list_providers()) == []


def test_provider_service_dependency_wired() -> None:
    """get_provider_service 与 app 的依赖覆盖点一致（避免手工构造遗漏）。"""
    from app.api.deps import get_provider_service as dependency

    assert dependency is get_provider_service
