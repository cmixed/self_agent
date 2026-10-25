"""技能 API 测试：CRUD 契约与保护规则。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.services.skill_service import BUILTIN_SKILL_IDS


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
    assert {skill["skill_id"] for skill in body["skills"]} == set(BUILTIN_SKILL_IDS)
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


def test_list_reports_resource_and_script_counts(client: TestClient) -> None:
    created = client.post(
        "/api/skills",
        json={"name": "带统计技能", "description": "说明", "content": "指令内容"},
    ).json()
    assert created["resource_count"] == 0
    assert created["script_count"] == 0

    skill_id = created["skill_id"]
    for name, body in (
        ("references/background.md", "背景"),
        ("resources/template.md", "模板"),
        ("scripts/collect.sh", "echo hi"),
    ):
        added = client.post(
            f"/api/skills/{skill_id}/resources", json={"name": name, "content": body}
        )
        assert added.status_code == 200

    listed = next(
        item for item in client.get("/api/skills").json()["skills"] if item["skill_id"] == skill_id
    )
    assert listed["resource_count"] == 3
    assert listed["script_count"] == 1


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
    # 扁平附件名会放进标准 resources/ 目录
    assert resource["name"] == "resources/checklist"

    duplicate = client.post(
        f"/api/skills/{skill_id}/resources",
        json={"name": "resources/checklist", "content": "重复"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_type"] == "skill_resource_name_conflict"

    listed = client.get(f"/api/skills/{skill_id}/resources")
    assert [item["resource_id"] for item in listed.json()["resources"]] == [resource["resource_id"]]

    updated = client.put(
        f"/api/skills/{skill_id}/resources/{resource['resource_id']}",
        json={"name": "resources/checklist-v2", "content": "检查项 B"},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "检查项 B"
    new_resource_id = updated.json()["resource_id"]
    assert new_resource_id == "resources/checklist-v2"

    deleted = client.delete(f"/api/skills/{skill_id}/resources/{new_resource_id}")
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
    builtin_id = BUILTIN_SKILL_IDS[0]

    blocked = seeded_client.delete(f"/api/skills/{builtin_id}")
    assert blocked.status_code == 409
    assert blocked.json()["error_type"] == "skill_builtin_protected"

    disabled = seeded_client.put(f"/api/skills/{builtin_id}", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False


def test_create_skill_validates_payload(client: TestClient) -> None:
    response = client.post("/api/skills", json={"name": "", "description": "d", "content": "c"})
    assert response.status_code == 422


def _skill_zip(name: str = "demo") -> bytes:
    import io
    import zipfile

    skill_md = (
        "---\n"
        "name: 导入技能\n"
        "description: 当需要验证技能包导入时使用\n"
        "---\n\n"
        "你是导入技能。请按步骤执行。\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{name}/SKILL.md", skill_md)
        archive.writestr(f"{name}/references/note.md", "附件正文")
        archive.writestr(f"{name}/scripts/run.py", "print('hi')\n")
    return buffer.getvalue()


def test_import_preview_and_confirm(client: TestClient) -> None:
    preview = client.post(
        "/api/skills/import/preview",
        files={"file": ("demo.zip", _skill_zip(), "application/zip")},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["name"] == "导入技能"
    assert body["suggested_skill_id"] == "demo"
    assert [item["name"] for item in body["resources"]] == [
        "references/note.md",
        "scripts/run.py",
    ]
    assert any("不会执行" in warning for warning in body["warnings"])
    token = body["token"]

    confirmed = client.post("/api/skills/import", json={"token": token})
    assert confirmed.status_code == 200
    skill = confirmed.json()
    assert skill["skill_id"] == "demo"
    assert skill["builtin"] is False

    resources = client.get("/api/skills/demo/resources").json()["resources"]
    assert [item["resource_id"] for item in resources] == [
        "references/note.md",
        "scripts/run.py",
    ]

    # token 一次性使用
    reused = client.post("/api/skills/import", json={"token": token})
    assert reused.status_code == 409
    assert reused.json()["error_type"] == "skill_import_expired"


def test_import_rejects_invalid_package(client: TestClient) -> None:
    response = client.post(
        "/api/skills/import/preview",
        files={"file": ("bad.zip", b"not a zip", "application/zip")},
    )
    assert response.status_code == 422
    assert response.json()["error_type"] == "skill_package_invalid"


def test_export_skill_package(client: TestClient) -> None:
    preview = client.post(
        "/api/skills/import/preview",
        files={"file": ("demo.zip", _skill_zip(), "application/zip")},
    )
    token = preview.json()["token"]
    client.post("/api/skills/import", json={"token": token})

    exported = client.get("/api/skills/demo/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    assert "demo.zip" in exported.headers["content-disposition"]

    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert set(archive.namelist()) == {
            "demo/SKILL.md",
            "demo/references/note.md",
            "demo/scripts/run.py",
        }


def test_export_missing_skill(client: TestClient) -> None:
    response = client.get("/api/skills/nope/export")
    assert response.status_code == 404
    assert response.json()["error_type"] == "skill_not_found"
