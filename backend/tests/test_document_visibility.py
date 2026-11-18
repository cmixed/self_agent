"""团队版：文档归属、可见范围与检索范围过滤。

覆盖：
1. 默认团队共享 → 其他成员可见；
2. 私有文档 → 仅上传者与管理员可见，且不进他人列表；
3. 切换可见范围 / 删除的权限边界（非上传者 403）；
4. 任务检索范围：all 会冻结为「我可访问的文档」，与私有文档互不越界。
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from fakes import FakeEmbeddingProvider
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_document_service
from app.api.tasks import _resolve_retrieval
from app.main import create_app
from app.memory.users import UserRecord
from app.models.schemas import TaskScope
from app.rag.store import ChromaStore
from app.services.category_service import CategoryService
from app.services.document_service import DocumentService

ALICE = UserRecord(
    user_id="u-alice",
    username="alice",
    display_name="Alice",
    email=None,
    role="member",
    status="active",
    created_at="2026-11-01T00:00:00+00:00",
    last_login_at=None,
)
BOB = UserRecord(
    user_id="u-bob",
    username="bob",
    display_name="Bob",
    email=None,
    role="member",
    status="active",
    created_at="2026-11-01T00:00:00+00:00",
    last_login_at=None,
)
ADMIN = UserRecord(
    user_id="u-admin",
    username="admin",
    display_name="管理员",
    email=None,
    role="admin",
    status="active",
    created_at="2026-11-01T00:00:00+00:00",
    last_login_at=None,
)


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, UserRecord]]:
    store = ChromaStore(
        persist_dir=tmp_path / "chroma",
        collection_name="visibility_kb",
        embedding_signature=FakeEmbeddingProvider().signature(),
    )
    service = DocumentService(
        provider_factory=lambda: FakeEmbeddingProvider(),
        store=store,
        documents_dir=tmp_path / "documents",
        chunk_size=120,
        chunk_overlap=20,
    )
    app = create_app()
    app.dependency_overrides[get_document_service] = lambda: service
    current = {"user": ALICE}
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    return TestClient(app), current


def upload(client: TestClient, name: str, visibility: str = "team") -> str:
    response = client.post(
        "/api/documents/upload",
        files={"file": (name, f"# {name}\n\n团队知识库内容".encode(), "text/markdown")},
        data={"visibility": visibility},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["visibility"] == visibility
    return body["document_id"]


def test_team_document_visible_to_others(tmp_path: Path) -> None:
    client, current = make_client(tmp_path)
    with client:
        document_id = upload(client, "shared.md", "team")

        current["user"] = BOB
        listed = client.get("/api/documents").json()["documents"]
        assert [item["document_id"] for item in listed] == [document_id]
        # 非上传者不能改范围、不能删
        assert (
            client.patch(
                f"/api/documents/{document_id}/visibility", json={"visibility": "private"}
            ).status_code
            == 403
        )
        assert client.delete(f"/api/documents/{document_id}").status_code == 403


def test_private_document_hidden_from_others(tmp_path: Path) -> None:
    client, current = make_client(tmp_path)
    with client:
        private_id = upload(client, "own.md", "private")

        current["user"] = BOB
        assert client.get("/api/documents").json()["documents"] == []

        current["user"] = ADMIN
        documents = client.get("/api/documents").json()["documents"]
        assert [item["document_id"] for item in documents] == [private_id]


def test_owner_can_toggle_visibility(tmp_path: Path) -> None:
    client, current = make_client(tmp_path)
    with client:
        document_id = upload(client, "toggle.md", "private")
        toggled = client.patch(
            f"/api/documents/{document_id}/visibility", json={"visibility": "team"}
        )
        assert toggled.status_code == 200
        assert toggled.json()["visibility"] == "team"

        current["user"] = BOB
        assert len(client.get("/api/documents").json()["documents"]) == 1


def test_invalid_visibility_rejected(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    with client:
        response = client.post(
            "/api/documents/upload",
            files={"file": ("x.md", b"# x", "text/markdown")},
            data={"visibility": "world"},
        )
    assert response.status_code == 422


class _StubCategories:
    """resolve_scope 的替身：只验证交集逻辑，不依赖 SQLite。"""

    def __init__(self, resolved: list[str]) -> None:
        self._resolved = resolved

    async def resolve_scope(self, *, category_ids, document_ids):
        return list(self._resolved)

    async def list_categories(self):
        return []


@pytest.mark.anyio
async def test_retrieval_all_freezes_visible_set() -> None:
    mode, scope = await _resolve_retrieval(
        None, cast(CategoryService, _StubCategories([])), "all", visible_ids={"d1", "d2"}
    )
    assert mode == "selected"
    assert scope is not None and scope.get("document_ids") == ["d1", "d2"]


@pytest.mark.anyio
async def test_retrieval_all_with_no_visible_documents_skips_retrieval() -> None:
    """成员一篇文档都看不到时不该被 409 挡住：按不检索执行，且不能退化成全库。"""
    mode, scope = await _resolve_retrieval(
        None, cast(CategoryService, _StubCategories([])), "all", visible_ids=set()
    )
    assert mode == "none"
    assert scope is None


@pytest.mark.anyio
async def test_retrieval_selected_intersects_visible() -> None:
    stub = _StubCategories(["d1", "d2", "d3"])
    requested = TaskScope(category_ids=[], document_ids=["d1", "d2", "d3"])
    mode, scope = await _resolve_retrieval(
        requested, cast(CategoryService, stub), "selected", visible_ids={"d1", "d3"}
    )
    assert mode == "selected"
    assert scope is not None and scope.get("document_ids") == ["d1", "d3"]


@pytest.mark.anyio
async def test_retrieval_selected_all_hidden_raises() -> None:
    stub = _StubCategories(["d9"])
    requested = TaskScope(category_ids=[], document_ids=["d9"])
    with pytest.raises(Exception) as exc:
        await _resolve_retrieval(
            requested, cast(CategoryService, stub), "selected", visible_ids={"d1"}
        )
    assert "没有任何文档" in str(exc.value)
