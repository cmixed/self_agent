"""预设任务：服务层与 API 契约。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.memory.sqlite import SqliteDatabase
from app.services.preset_service import (
    DEFAULT_PRESETS,
    DEFAULT_VERBATIM_PRESETS,
    PresetNotFoundError,
    PresetOrderError,
    PresetService,
)


@pytest.fixture
def service(tmp_path) -> PresetService:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    return PresetService(database)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


async def test_verbatim_defaults_seeded_for_existing_install(
    service: PresetService,
) -> None:
    """旧安装只有生成预设 marker 时，升级后应补上两条原文预设。"""
    # 模拟旧版本：只写过生成内容默认预设
    await service._repository.seed_once(DEFAULT_PRESETS)  # noqa: SLF001 - 测试旧 marker 状态
    assert await service.list_presets("verbatim") == []

    await service.ensure_seeded()

    generated = await service.list_presets("generate")
    verbatim = await service.list_presets("verbatim")
    assert {item.preset_id for item in generated} == {seed["preset_id"] for seed in DEFAULT_PRESETS}
    assert {item.preset_id for item in verbatim} == {
        seed["preset_id"] for seed in DEFAULT_VERBATIM_PRESETS
    }


async def test_seed_once_writes_defaults(service: PresetService) -> None:
    await service.ensure_seeded()
    generated = await service.list_presets("generate")
    verbatim = await service.list_presets("verbatim")

    assert {item.preset_id for item in generated} == {seed["preset_id"] for seed in DEFAULT_PRESETS}
    assert {item.preset_id for item in verbatim} == {
        seed["preset_id"] for seed in DEFAULT_VERBATIM_PRESETS
    }
    assert all(item.output_mode == "verbatim" for item in verbatim)


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
        seed["preset_id"] for seed in [*DEFAULT_PRESETS, *DEFAULT_VERBATIM_PRESETS]
    }
    verbatim = client.get("/api/presets?output_mode=verbatim").json()["presets"]
    assert {item["preset_id"] for item in verbatim} == {
        seed["preset_id"] for seed in DEFAULT_VERBATIM_PRESETS
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
    blank_title = client.post("/api/presets", json={"title": "", "description": "d", "query": "q"})
    blank_query = client.post("/api/presets", json={"title": "t", "description": "d", "query": ""})
    assert blank_title.status_code == 422
    assert blank_query.status_code == 422


async def test_preset_scope_and_auto_run_roundtrip(service: PresetService) -> None:
    await service.ensure_seeded()

    created = await service.create_preset(
        title="范围任务",
        description="只在指定范围检索",
        query="整理指定范围的资料",
        category_ids=["cat-1"],
        document_ids=["doc-1"],
        auto_run=True,
    )
    assert created.category_ids == ["cat-1"]
    assert created.document_ids == ["doc-1"]
    assert created.auto_run is True

    reloaded = {item.preset_id: item for item in await service.list_presets()}[created.preset_id]
    assert reloaded.category_ids == ["cat-1"]
    assert reloaded.document_ids == ["doc-1"]
    assert reloaded.auto_run is True

    # 未传范围：只改标题，范围保持不变
    renamed = await service.update_preset(created.preset_id, title="改名")
    assert renamed.title == "改名"
    assert renamed.category_ids == ["cat-1"]

    # 传空列表：清除绑定；关闭直接运行
    cleared = await service.update_preset(
        created.preset_id, category_ids=[], document_ids=[], auto_run=False
    )
    assert cleared.category_ids == []
    assert cleared.document_ids == []
    assert cleared.auto_run is False


async def test_seeded_presets_are_unbound(service: PresetService) -> None:
    await service.ensure_seeded()
    presets = await service.list_presets()
    assert presets  # 默认预设存在
    assert all(not item.category_ids and not item.document_ids for item in presets)
    assert all(item.auto_run is False for item in presets)


def test_preset_scope_and_auto_run_api(client: TestClient) -> None:
    created = client.post(
        "/api/presets",
        json={
            "title": "范围预设",
            "description": "d",
            "query": "q",
            "scope": {"category_ids": ["c1"], "document_ids": ["d1"]},
            "auto_run": True,
        },
    )
    assert created.status_code == 200
    preset = created.json()
    assert preset["scope"] == {"category_ids": ["c1"], "document_ids": ["d1"]}
    assert preset["auto_run"] is True

    # 未提供 scope：保持不变
    renamed = client.put(f"/api/presets/{preset['preset_id']}", json={"title": "改名"})
    assert renamed.status_code == 200
    assert renamed.json()["scope"] == {"category_ids": ["c1"], "document_ids": ["d1"]}

    # 显式 null：清除绑定范围
    cleared = client.put(f"/api/presets/{preset['preset_id']}", json={"scope": None})
    assert cleared.status_code == 200
    assert cleared.json()["scope"] is None


async def test_presets_are_separated_by_output_mode(service: PresetService) -> None:
    generated = await service.create_preset(
        title="生成内容预设", description="写内容", query="写一篇综述"
    )
    verbatim = await service.create_preset(
        title="原文预设", description="输出原文", query="输出资料原文", output_mode="verbatim"
    )

    assert generated.output_mode == "generate"
    assert verbatim.output_mode == "verbatim"
    # 两种模式的排序互不影响：各自从 0 开始
    assert generated.sort_order == 0
    assert verbatim.sort_order == 0
    assert [item.preset_id for item in await service.list_presets("generate")] == [
        generated.preset_id
    ]
    assert [item.preset_id for item in await service.list_presets("verbatim")] == [
        verbatim.preset_id
    ]

    # 原文列表只需提交原文预设 id
    reordered = await service.reorder_presets([verbatim.preset_id], output_mode="verbatim")
    assert [item.preset_id for item in reordered] == [verbatim.preset_id]

    # 切换输出方式 = 移动到另一组末尾
    moved = await service.update_preset(generated.preset_id, output_mode="verbatim")
    assert moved.output_mode == "verbatim"
    assert moved.sort_order == 1
    assert {item.preset_id for item in await service.list_presets("verbatim")} == {
        generated.preset_id,
        verbatim.preset_id,
    }
    assert await service.list_presets("generate") == []


def test_preset_api_filters_by_output_mode(client: TestClient) -> None:
    created = client.post(
        "/api/presets",
        json={
            "title": "输出原文",
            "description": "直接读取知识库原文",
            "query": "输出资料原文",
            "output_mode": "verbatim",
        },
    )
    assert created.status_code == 200
    preset = created.json()
    assert preset["output_mode"] == "verbatim"

    verbatim = client.get("/api/presets?output_mode=verbatim").json()["presets"]
    generated = client.get("/api/presets?output_mode=generate").json()["presets"]
    all_presets = client.get("/api/presets").json()["presets"]

    assert any(item["preset_id"] == preset["preset_id"] for item in verbatim)
    assert all(item["output_mode"] == "verbatim" for item in verbatim)
    assert all(item["output_mode"] == "generate" for item in generated)
    assert len(all_presets) == len(generated) + len(verbatim)


async def test_new_presets_append_to_end(service: PresetService) -> None:
    await service.ensure_seeded()
    seeded = await service.list_presets("generate")
    assert [item.sort_order for item in seeded] == list(range(len(seeded)))

    created = await service.create_preset(
        title="新预设", description="追加到末尾", query="执行新预设"
    )
    assert created.sort_order == len(seeded)
    assert (await service.list_presets("generate"))[-1].preset_id == created.preset_id


async def test_reorder_presets_persists_order(service: PresetService) -> None:
    await service.ensure_seeded()
    presets = await service.list_presets("generate")
    reversed_ids = [item.preset_id for item in reversed(presets)]

    reordered = await service.reorder_presets(reversed_ids)

    assert [item.preset_id for item in reordered] == reversed_ids
    assert [item.sort_order for item in reordered] == list(range(len(presets)))
    assert [item.preset_id for item in await service.list_presets("generate")] == reversed_ids


async def test_reorder_requires_exact_id_set(service: PresetService) -> None:
    await service.ensure_seeded()
    presets = await service.list_presets("generate")
    ids = [item.preset_id for item in presets]

    with pytest.raises(PresetOrderError):
        await service.reorder_presets(ids[:-1])

    with pytest.raises(PresetOrderError):
        await service.reorder_presets([*ids, "missing"])

    with pytest.raises(PresetOrderError):
        await service.reorder_presets([ids[0], ids[0], *ids[1:]])


def test_reorder_api_roundtrip_and_conflict(client: TestClient) -> None:
    presets = client.get("/api/presets?output_mode=generate").json()["presets"]
    reversed_ids = [item["preset_id"] for item in reversed(presets)]

    response = client.put(
        "/api/presets/order",
        json={"preset_ids": reversed_ids, "output_mode": "generate"},
    )
    assert response.status_code == 200
    body = response.json()["presets"]
    assert [item["preset_id"] for item in body] == reversed_ids
    assert [item["sort_order"] for item in body] == list(range(len(presets)))

    conflict = client.put(
        "/api/presets/order",
        json={"preset_ids": reversed_ids[:-1], "output_mode": "generate"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_type"] == "preset_order_conflict"


def test_presets_sort_order_migration_is_idempotent(tmp_path) -> None:
    path = tmp_path / "app.db"
    # 模拟旧库：presets 已存在且没有 sort_order
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE presets (
                preset_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                query TEXT NOT NULL,
                auto_run INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO presets(preset_id, title, description, query, created_at, updated_at)
            VALUES ('old', '旧预设', '说明', '任务', '2026-01-01T00:00:00+00:00',
                    '2026-01-01T00:00:00+00:00')
            """
        )

    database = SqliteDatabase(path)
    database.initialize()
    database.initialize()

    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(presets)")}
        row = connection.execute(
            "SELECT sort_order FROM presets WHERE preset_id = 'old'"
        ).fetchone()
    assert "sort_order" in columns
    assert row["sort_order"] == 0
