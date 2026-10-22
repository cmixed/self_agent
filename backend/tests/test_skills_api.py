"""技能 API 测试：CRUD 契约与保护规则。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.services.skill_service import BUILTIN_SKILLS


@pytest.fixture
def client() -> Iterator[TestClient]:
    # 用上下文管理器触发 lifespan：建表（默认不 seed 内置技能）
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def seeded_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """显式开启内置技能 seed 的客户端。"""
    monkeypatch.setenv("SEED_BUILTIN_SKILLS", "true")
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client


def test_list_skills_does_not_seed_builtin_by_default(client: TestClient) -> None:
    response = client.get("/api/skills")
    assert response.status_code == 200
    assert response.json()["skills"] == []


def test_list_skills_seeds_builtin_on_startup(seeded_client: TestClient) -> None:
    response = seeded_client.get("/api/skills")
    assert response.status_code == 200
    body = response.json()
    assert {skill["skill_id"] for skill in body["skills"]} == {
        seed["skill_id"] for seed in BUILTIN_SKILLS
    }
    assert all(skill["builtin"] for skill in body["skills"])


def test_create_update_delete_skill(client: TestClient) -> None:
    created = client.post(
        "/api/skills",
        json={"name": "自定义技能", "description": "说明", "content": "指令内容"},
    )
    assert created.status_code == 200
    skill = created.json()
    assert skill["builtin"] is False

    updated = client.put(
        f"/api/skills/{skill['skill_id']}", json={"enabled": False, "name": "改名"}
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False
    assert updated.json()["name"] == "改名"

    deleted = client.delete(f"/api/skills/{skill['skill_id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted"}

    missing = client.delete(f"/api/skills/{skill['skill_id']}")
    assert missing.status_code == 404
    assert missing.json()["error_type"] == "skill_not_found"


def test_skill_resource_crud(client: TestClient) -> None:
    created = client.post(
        "/api/skills",
        json={"name": "带附件技能", "description": "说明", "content": "指令内容"},
    )
    skill_id = created.json()["skill_id"]

    empty = client.get(f"/api/skills/{skill_id}/resources")
    assert empty.status_code == 200
    assert empty.json()["resources"] == []

    added = client.post(
        f"/api/skills/{skill_id}/resources",
        json={"name": "checklist", "content": "检查项 A"},
    )
    assert added.status_code == 200
    resource = added.json()
    assert resource["name"] == "checklist"

    duplicate = client.post(
        f"/api/skills/{skill_id}/resources",
        json={"name": "checklist", "content": "重复"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_type"] == "skill_resource_name_conflict"

    listed = client.get(f"/api/skills/{skill_id}/resources")
    assert [item["resource_id"] for item in listed.json()["resources"]] == [resource["resource_id"]]

    updated = client.put(
        f"/api/skills/{skill_id}/resources/{resource['resource_id']}",
        json={"name": "checklist-v2", "content": "检查项 B"},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "检查项 B"

    deleted = client.delete(f"/api/skills/{skill_id}/resources/{resource['resource_id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/skills/{skill_id}/resources").json()["resources"] == []


def test_skill_resource_is_removed_with_skill(client: TestClient) -> None:
    created = client.post(
        "/api/skills",
        json={"name": "临时技能", "description": "说明", "content": "指令内容"},
    )
    skill_id = created.json()["skill_id"]
    added = client.post(
        f"/api/skills/{skill_id}/resources",
        json={"name": "note", "content": "附件正文"},
    )
    resource_id = added.json()["resource_id"]

    assert client.delete(f"/api/skills/{skill_id}").status_code == 200
    missing = client.get(f"/api/skills/{skill_id}/resources")
    assert missing.status_code == 404
    assert missing.json()["error_type"] == "skill_not_found"

    # 附件记录也不会残留在其它入口
    orphan = client.delete(f"/api/skills/{skill_id}/resources/{resource_id}")
    assert orphan.status_code == 404


def test_builtin_skill_cannot_be_deleted_but_can_be_disabled(
    seeded_client: TestClient,
) -> None:
    builtin_id = BUILTIN_SKILLS[0]["skill_id"]

    blocked = seeded_client.delete(f"/api/skills/{builtin_id}")
    assert blocked.status_code == 409
    assert blocked.json()["error_type"] == "skill_builtin_protected"

    disabled = seeded_client.put(f"/api/skills/{builtin_id}", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False


def test_create_skill_validates_payload(client: TestClient) -> None:
    response = client.post("/api/skills", json={"name": "", "description": "d", "content": "c"})
    assert response.status_code == 422
