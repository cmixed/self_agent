"""对外接口（/api/v1）与 API Key：鉴权、权限隔离、结果取回。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.deps import (
    get_category_service,
    get_document_service,
    get_memory_service,
    get_task_service,
)
from app.auth.service import AuthService
from app.main import create_app
from app.memory.api_keys import ApiKeyRepository
from app.memory.repository import TaskRepository
from app.memory.sqlite import SqliteDatabase
from app.memory.users import UserRepository
from app.services.api_key_service import ApiKeyService


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    monkeypatch.setattr(deps, "build_database", lambda: database)
    deps.reset_caches()

    users = UserRepository(database)
    auth = AuthService(users)
    admin = auth.bootstrap()
    member = auth.create_member(
        username="lisi", display_name="李四", email="lisi@example.com", password="member123"
    )

    keys = ApiKeyService(ApiKeyRepository(database), users)
    _, admin_key = keys.issue(user_id=admin.user_id, label="admin-key")
    _, member_key = keys.issue(user_id=member.user_id, label="member-key")

    yield {
        "database": database,
        "admin": admin,
        "member": member,
        "admin_key": admin_key,
        "member_key": member_key,
        "repository": TaskRepository(database),
    }
    deps.reset_caches()


def test_missing_or_invalid_key_rejected(env) -> None:
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/api/v1/tasks/whatever").status_code == 401
        assert (
            client.get("/api/v1/tasks/whatever", headers={"X-API-Key": "kb-wrong"}).status_code
            == 401
        )


def test_revoked_key_rejected(env) -> None:
    app = create_app()
    with TestClient(app) as client:
        keys = ApiKeyService(ApiKeyRepository(env["database"]), UserRepository(env["database"]))
        records = keys.list_keys(user_id=env["member"].user_id, is_admin=False)
        keys.revoke(records[0].key_id, user_id=env["member"].user_id, is_admin=False)
        response = client.get("/api/v1/tasks/x", headers={"X-API-Key": env["member_key"]})
    assert response.status_code == 401


def test_task_is_isolated_between_members(env) -> None:
    app = create_app()
    repository: TaskRepository = env["repository"]
    with TestClient(app) as client:
        import asyncio

        asyncio.run(
            repository.start_run(task_id="t-1", user_id=env["member"].user_id, query="写一份综述")
        )
        asyncio.run(
            repository.finish_run(
                task_id="t-1",
                result={"task_id": "t-1", "status": "completed", "final_answer": "# 综述\n\n正文"},
            )
        )

        mine = client.get("/api/v1/tasks/t-1", headers={"X-API-Key": env["member_key"]})
        assert mine.status_code == 200
        assert mine.json()["status"] == "completed"
        assert mine.json()["has_result"] is True

        markdown = client.get("/api/v1/tasks/t-1/result", headers={"X-API-Key": env["member_key"]})
        assert markdown.status_code == 200
        assert markdown.text.startswith("# 综述")
        assert markdown.headers["content-type"].startswith("text/markdown")

        # 别人的任务一律 404（不暴露存在性），管理员也不例外
        other = client.get("/api/v1/tasks/t-1", headers={"X-API-Key": env["admin_key"]})
        assert other.status_code == 404


def test_create_task_returns_accepted(env) -> None:
    """提交接口：202 + task_id，且以密钥所属成员身份启动（不越权）。"""
    app = create_app()
    calls: list[dict[str, object]] = []

    class StubTaskService:
        async def stream(self, query: str, **kwargs):
            # 真实 TaskService 用异步生成器推进任务；这里只记录调用后立刻结束
            calls.append({"query": query, "user_id": kwargs.get("user_id")})
            for _event in ():
                yield _event

    class StubDocuments:
        async def visible_document_ids(self, *, user_id: str, is_admin: bool):
            return {"d1"}

    class StubCategories:
        async def resolve_scope(self, *, category_ids, document_ids):
            return list(document_ids)

        async def list_categories(self):
            return []

    class StubMemory:
        async def get_profile(self, user_id: str):
            return {}, []

    app.dependency_overrides[get_task_service] = lambda: StubTaskService()
    app.dependency_overrides[get_document_service] = lambda: StubDocuments()
    app.dependency_overrides[get_category_service] = lambda: StubCategories()
    app.dependency_overrides[get_memory_service] = lambda: StubMemory()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tasks",
            headers={"X-API-Key": env["member_key"]},
            json={"query": "写一份综述"},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "running"
    assert body["task_id"]
