"""预设任务：服务层与 API 契约。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.memory.sqlite import SqliteDatabase
from app.services.preset_service import DEFAULT_PRESETS, PresetNotFoundError, PresetService


@pytest.fixture
def service(tmp_path) -> PresetService:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    return PresetService(database)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


async def test_seed_once_writes_defaults(service: PresetService) -> None:
    await service.ensure_seeded()
    presets = await service.list_presets()
    assert {item.preset_id for item in presets} == {seed["preset_id"] for seed in DEFAULT_PRESETS}


async def test_deleted_presets_do_not_come_back(service: PresetService) -> None:
    """删空预设后再次启动（再 seed）不应复活默认预设。"""
    await service.ensure_seeded()
    for item in await service.list_presets():
        await service.delete_preset(item.preset_id)

    await service.ensure_seeded()

    assert await service.list_presets() == []


async def test_crud(service: PresetService) -> None:
    await service.ensure_seeded()

    created = await service.create_preset(
        title="周报整理", description="把本周资料整理成周报", query="根据我本周的资料生成周报"
    )
    updated = await service.update_preset(created.preset_id, title="周报生成", query="生成周报")
    assert updated is not None
    assert updated.title == "周报生成"
    assert updated.query == "生成周报"
    assert updated.description == created.description  # 未传字段保持不变

    await service.delete_preset(created.preset_id)
    with pytest.raises(PresetNotFoundError):
        await service.update_preset(created.preset_id, title="x")


def test_list_presets_seeded_on_startup(client: TestClient) -> None:
    body = client.get("/api/presets").json()
    assert {item["preset_id"] for item in body["presets"]} == {
        seed["preset_id"] for seed in DEFAULT_PRESETS
    }


def test_preset_crud_api(client: TestClient) -> None:
    created = client.post(
        "/api/presets",
        json={"title": "自定义预设", "description": "说明", "query": "执行这个任务"},
    )
    assert created.status_code == 200
    preset = created.json()

    updated = client.put(f"/api/presets/{preset['preset_id']}", json={"title": "改名"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "改名"

    assert client.delete(f"/api/presets/{preset['preset_id']}").status_code == 200
    missing = client.delete(f"/api/presets/{preset['preset_id']}")
    assert missing.status_code == 404
    assert missing.json()["error_type"] == "preset_not_found"


def test_preset_requires_title_and_query(client: TestClient) -> None:
    blank_title = client.post(
        "/api/presets", json={"title": "", "description": "d", "query": "q"}
    )
    blank_query = client.post(
        "/api/presets", json={"title": "t", "description": "d", "query": ""}
    )
    assert blank_title.status_code == 422
    assert blank_query.status_code == 422
