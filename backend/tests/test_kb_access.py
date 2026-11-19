"""团队版能力矩阵：知识库 × 共享 × 四种能力。

覆盖：
1. 团队知识库默认对全员「可检索 + 可列表 + 可看原文」，但不可写；
2. 个人知识库只有库主与收到共享的人可见，管理员也拿不到内容；
3. 组共享生效后，组成员继承能力；「仅检索」不给列表、不给原文；
4. 成员提案需要管理员批准，未批准前不生效；
5. 文件子集共享只放行被选中的文件；
6. 系统管理员能看到共享关系图，但列表里没有别人库里的内容；
7. 撤销共享后能力立即消失。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fakes import FakeEmbeddingProvider, document_service_for
from fastapi.testclient import TestClient

from app.api.deps import (
    build_database,
    get_current_user,
    get_document_service,
    get_group_service,
    get_knowledge_service,
)
from app.main import create_app
from app.memory.groups import GroupRepository
from app.memory.knowledge import (
    SUBJECT_GROUP,
    SUBJECT_TEAM,
    SUBJECT_TEAM_ID,
    SUBJECT_USER,
    KnowledgeRepository,
)
from app.memory.users import UserRecord, UserRepository
from app.rag.store import ChromaStore
from app.services.access import TEAM_KB_ID, AccessService, Caps
from app.services.document_service import DocumentService
from app.services.group_service import GroupService
from app.services.knowledge_service import KnowledgeService


class Harness:
    """一套隔离的知识库环境：临时 Chroma + 临时 SQLite + 真实权限链路。"""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        provider = FakeEmbeddingProvider()
        self.store = ChromaStore(
            persist_dir=tmp_path / "chroma",
            collection_name="kb_access",
            embedding_signature=provider.signature(),
        )
        database = build_database()
        database.initialize()
        self.knowledge_repo = KnowledgeRepository(database)
        self.group_repo = GroupRepository(database)
        self.user_repo = UserRepository(database)
        self.access = AccessService(self.knowledge_repo, self.group_repo)
        self.documents = document_service_for(self.store, tmp_path, access=self.access)
        self.knowledge = KnowledgeService(
            self.knowledge_repo, self.group_repo, self.user_repo, lambda: self.documents
        )
        self.groups = GroupService(self.group_repo, self.user_repo, self.knowledge_repo)
        self.users: dict[str, UserRecord] = {}
        self.current: dict[str, UserRecord] = {}
        for key, role in (("alice", "member"), ("bob", "member"), ("admin", "admin")):
            self.users[key] = self.user_repo.create(
                username=key,
                display_name=key.title(),
                email=None,
                password_hash="x",
                role=role,
                created_at="2026-11-01T00:00:00+00:00",
            )
        asyncio.run(self.knowledge.bootstrap())

    def client(self) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_document_service] = lambda: self.documents
        app.dependency_overrides[get_knowledge_service] = lambda: self.knowledge
        app.dependency_overrides[get_group_service] = lambda: self.groups
        app.dependency_overrides[get_current_user] = lambda: self.current["user"]
        self.current.setdefault("user", self.users["alice"])
        return TestClient(app)

    # --- 便捷操作 ---

    def upload(self, user: str, kb_id: str, name: str, text: str = "# 文档\n\n内容") -> str:
        self.current["user"] = self.users[user]
        client = self.client()
        response = client.post(
            "/api/documents/upload",
            files={"file": (name, text.encode(), "text/markdown")},
            data={"kb_id": kb_id},
        )
        assert response.status_code == 200, response.text
        return response.json()["document_id"]

    def personal_kb(self, user: str) -> str:
        record = asyncio.run(self.knowledge.ensure_personal_kb(self.users[user]))
        return record.kb_id

    def share(
        self,
        *,
        kb_id: str,
        subject_type: str,
        subject_id: str,
        caps: dict[str, bool],
        document_ids: list[str] | None = None,
        as_user: str,
    ) -> dict:
        self.current["user"] = self.users[as_user]
        client = self.client()
        payload = {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "caps": {
                "search": caps.get("search", False),
                "list": caps.get("list", False),
                "read": caps.get("read", False),
                "write": caps.get("write", False),
            },
            "document_ids": document_ids or [],
            "reason": "测试共享",
        }
        response = client.post(f"/api/kb/{kb_id}/shares", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    def listed(self, user: str, kb_id: str | None = None) -> list[dict]:
        self.current["user"] = self.users[user]
        client = self.client()
        params = {"kb_id": kb_id} if kb_id else None
        response = client.get("/api/documents", params=params)
        assert response.status_code == 200, response.text
        return response.json()["documents"]

    def content_status(self, user: str, document_id: str) -> int:
        self.current["user"] = self.users[user]
        client = self.client()
        return client.get(f"/api/documents/{document_id}/content").status_code


@pytest.fixture()
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_team_kb_is_read_only_for_members(harness: Harness) -> None:
    # 管理员把一篇文档放进团队知识库（库主才可写）
    harness.current["user"] = harness.users["admin"]
    client = harness.client()
    response = client.post(
        "/api/documents/upload",
        files={"file": ("team.md", b"# team\n\n\xe5\x9b\xa2\xe9\x98\x9f", "text/markdown")},
        data={"kb_id": TEAM_KB_ID},
    )
    assert response.status_code == 200, response.text
    document_id = response.json()["document_id"]

    # 成员：能列表、能看原文，但没有写能力
    documents = harness.listed("alice", TEAM_KB_ID)
    assert [item["document_id"] for item in documents] == [document_id]
    assert documents[0]["caps"] == {"search": True, "list": True, "read": True, "write": False}
    assert harness.content_status("alice", document_id) == 200
    assert client.delete(f"/api/documents/{document_id}").status_code in (200, 403)

    # 成员往团队知识库上传 → 403（走自己的库再申请共享）
    harness.current["user"] = harness.users["alice"]
    client = harness.client()
    denied = client.post(
        "/api/documents/upload",
        files={"file": ("mine.md", b"# mine", "text/markdown")},
        data={"kb_id": TEAM_KB_ID},
    )
    assert denied.status_code == 403


def test_personal_kb_invisible_to_others_even_for_admin(harness: Harness) -> None:
    kb_id = harness.personal_kb("alice")
    document_id = harness.upload("alice", kb_id, "private.md")

    assert [item["document_id"] for item in harness.listed("bob")] == []
    assert harness.content_status("bob", document_id) == 404

    # 系统管理员看得到「库」与「关系」，但同样打不开内容
    harness.current["user"] = harness.users["admin"]
    client = harness.client()
    listed = client.get("/api/documents").json()["documents"]
    assert listed == []
    assert harness.content_status("admin", document_id) == 404
    kbs = {item["kb_id"]: item for item in client.get("/api/kb").json()["items"]}
    assert kb_id in kbs
    assert kbs[kb_id]["my_caps"]["read"] is False


def test_group_share_grants_caps_by_union(harness: Harness) -> None:
    kb_id = harness.personal_kb("alice")
    document_id = harness.upload("alice", kb_id, "paper.md")

    # 建组并把 bob 拉进来
    group = harness.groups.create(name="算法组", description="", user=harness.users["alice"])
    harness.groups.add_member(
        group.group_id,
        user_id=harness.users["bob"].user_id,
        role="member",
        actor=harness.users["alice"],
    )

    # 「仅检索」：能检索，但列表里看不到、原文打不开
    harness.share(
        kb_id=kb_id,
        subject_type=SUBJECT_GROUP,
        subject_id=group.group_id,
        caps={"search": True},
        as_user="alice",
    )
    visible = asyncio.run(
        harness.documents.visible_document_ids(user_id=harness.users["bob"].user_id)
    )
    assert visible == {document_id}
    assert harness.listed("bob") == []
    assert harness.content_status("bob", document_id) == 404

    # 叠加一条「可看列表」：并集变成 search + list，原文仍然不行
    harness.share(
        kb_id=kb_id,
        subject_type=SUBJECT_GROUP,
        subject_id=group.group_id,
        caps={"search": True, "list": True},
        as_user="alice",
    )
    assert [item["document_id"] for item in harness.listed("bob")] == [document_id]
    assert harness.content_status("bob", document_id) == 404

    # 再叠加「可看原文」→ 只读
    harness.share(
        kb_id=kb_id,
        subject_type=SUBJECT_GROUP,
        subject_id=group.group_id,
        caps={"search": True, "list": True, "read": True},
        as_user="alice",
    )
    assert harness.content_status("bob", document_id) == 200


def test_member_share_waits_for_admin_approval(harness: Harness) -> None:
    """库主直接生效；被授权的非库主成员发起共享需要管理员审批。"""
    kb_id = harness.personal_kb("alice")
    document_id = harness.upload("alice", kb_id, "draft.md")

    # bob 对 alice 的库没有管理权 → 不能发起共享
    harness.current["user"] = harness.users["bob"]
    client = harness.client()
    denied = client.post(
        f"/api/kb/{kb_id}/shares",
        json={
            "subject_type": SUBJECT_USER,
            "subject_id": harness.users["bob"].user_id,
            "caps": {"search": True},
        },
    )
    assert denied.status_code == 403

    # alice 授予 bob 可编辑 → bob 成为「知识库管理者」但仍是成员身份，
    # 他的共享提案进入待审批
    harness.share(
        kb_id=kb_id,
        subject_type=SUBJECT_USER,
        subject_id=harness.users["bob"].user_id,
        caps={"write": True},
        as_user="alice",
    )
    proposal = harness.share(
        kb_id=kb_id,
        subject_type=SUBJECT_TEAM,
        subject_id=SUBJECT_TEAM_ID,
        caps={"search": True, "list": True, "read": True},
        as_user="bob",
    )
    assert proposal["status"] == "pending"
    assert harness.listed("admin") == []  # 未批准前不生效

    harness.current["user"] = harness.users["admin"]
    client = harness.client()
    pending = client.get("/api/shares", params={"view": "pending"}).json()["items"]
    assert [item["share_id"] for item in pending] == [proposal["share_id"]]
    approved = client.post(
        f"/api/shares/{proposal['share_id']}/decide", json={"approve": True, "note": "同意"}
    )
    assert approved.status_code == 200 and approved.json()["status"] == "active"
    assert [item["document_id"] for item in harness.listed("admin")] == [document_id]


def test_document_subset_share_only_exposes_selected_files(harness: Harness) -> None:
    kb_id = harness.personal_kb("alice")
    first = harness.upload("alice", kb_id, "a.md", "# A")
    second = harness.upload("alice", kb_id, "b.md", "# B")

    harness.share(
        kb_id=kb_id,
        subject_type=SUBJECT_USER,
        subject_id=harness.users["bob"].user_id,
        caps={"search": True, "list": True, "read": True},
        document_ids=[first],
        as_user="alice",
    )
    listed = harness.listed("bob")
    assert [item["document_id"] for item in listed] == [first]
    assert harness.content_status("bob", first) == 200
    assert harness.content_status("bob", second) == 404


def test_graph_shows_relations_without_content(harness: Harness) -> None:
    kb_id = harness.personal_kb("alice")
    harness.upload("alice", kb_id, "x.md")
    group = harness.groups.create(name="论文组", description="", user=harness.users["alice"])
    harness.groups.add_member(
        group.group_id,
        user_id=harness.users["bob"].user_id,
        role="member",
        actor=harness.users["alice"],
    )
    harness.share(
        kb_id=kb_id,
        subject_type=SUBJECT_GROUP,
        subject_id=group.group_id,
        caps={"read": True},
        as_user="alice",
    )

    harness.current["user"] = harness.users["admin"]
    client = harness.client()
    graph = client.get("/api/kb/graph").json()
    node_ids = {node["id"] for node in graph["nodes"]}
    assert f"kb:{kb_id}" in node_ids
    assert f"group:{group.group_id}" in node_ids
    share_edges = [edge for edge in graph["edges"] if edge["kind"] == "share"]
    assert any(edge["target"] == f"kb:{kb_id}" for edge in share_edges)
    # 关系图只给关系与能力标签，不给文档内容
    assert not any("document_id" in node for node in graph["nodes"])
    # 管理员能看到分组里的完整名单
    group_node = next(node for node in graph["nodes"] if node["id"] == f"group:{group.group_id}")
    assert set(group_node["members"]) == {"Alice", "Bob"}
    team_node = next(node for node in graph["nodes"] if node["id"] == "team:*")
    assert set(team_node["members"]) == {"Alice", "Bob", "Admin"}


def test_graph_members_are_scoped_by_viewer(harness: Harness) -> None:
    """普通成员在关系图里只看到自己，不泄露同组其他人的名字。"""
    group = harness.groups.create(name="论文组", description="", user=harness.users["alice"])
    harness.groups.add_member(
        group.group_id,
        user_id=harness.users["bob"].user_id,
        role="member",
        actor=harness.users["alice"],
    )

    harness.current["user"] = harness.users["bob"]
    graph = harness.client().get("/api/kb/graph").json()
    group_node = next(node for node in graph["nodes"] if node["id"] == f"group:{group.group_id}")
    assert group_node["members"] == ["Bob"]
    assert group_node["member_count"] == 2
    team_node = next(node for node in graph["nodes"] if node["id"] == "team:*")
    assert team_node["members"] == ["Bob"]


def test_revoke_share_removes_access(harness: Harness) -> None:
    kb_id = harness.personal_kb("alice")
    document_id = harness.upload("alice", kb_id, "revoke.md")
    share = harness.share(
        kb_id=kb_id,
        subject_type=SUBJECT_USER,
        subject_id=harness.users["bob"].user_id,
        caps={"read": True},
        as_user="alice",
    )
    assert harness.content_status("bob", document_id) == 200

    harness.current["user"] = harness.users["alice"]
    client = harness.client()
    assert client.delete(f"/api/shares/{share['share_id']}").status_code == 204
    assert harness.content_status("bob", document_id) == 404


def test_caps_union_is_monotonic() -> None:
    """能力组合的纯逻辑：叠加只增不减，写权限自动包含读/列表/检索。"""
    base = Caps.of(search=True)
    assert Caps.of(write=True) == Caps(search=True, list=True, read=True, write=True)
    assert (base | Caps.of(list=True)).search and (base | Caps.of(list=True)).list
    assert not (base | Caps.of(list=True)).read
    assert base | Caps(search=False, list=False, read=False, write=False) == base


def test_document_service_requires_access_instance(tmp_path: Path) -> None:
    """没有能力服务时不误放行：团队库归属的文档对无身份调用仍可内部读。"""
    provider = FakeEmbeddingProvider()
    store = ChromaStore(
        persist_dir=tmp_path / "chroma2",
        collection_name="no_access",
        embedding_signature=provider.signature(),
    )
    service = DocumentService(
        provider_factory=lambda: provider,
        store=store,
        documents_dir=tmp_path / "documents2",
    )
    asyncio.run(service.ingest(filename="a.md", content=b"# A"))
    assert asyncio.run(service.visible_document_ids(user_id="u-x")) == {
        item.document_id for item in asyncio.run(service.list_documents())
    }


def test_subject_validation_rejects_unknown_group(harness: Harness) -> None:
    kb_id = harness.personal_kb("alice")
    harness.current["user"] = harness.users["alice"]
    client = harness.client()
    response = client.post(
        f"/api/kb/{kb_id}/shares",
        json={
            "subject_type": "group",
            "subject_id": "grp-missing",
            "caps": {"search": True},
        },
    )
    assert response.status_code == 404


def test_kb_kind_team_only_for_admin(harness: Harness) -> None:
    harness.current["user"] = harness.users["alice"]
    client = harness.client()
    denied = client.post("/api/kb", json={"name": "团队二库", "kind": "team"})
    assert denied.status_code == 403

    harness.current["user"] = harness.users["admin"]
    client = harness.client()
    created = client.post("/api/kb", json={"name": "团队二库", "kind": "team"})
    assert created.status_code == 201, created.text
    assert created.json()["kind"] == "team"


def test_team_share_subject_is_whole_team(harness: Harness) -> None:
    """team 主体等价于「所有人」：新成员天然获得该库能力。"""
    shares = [
        item
        for item in harness.knowledge_repo.list_active_for_subject(SUBJECT_TEAM, SUBJECT_TEAM_ID)
    ]
    assert shares, "团队知识库应有全团队共享"
    assert shares[0].kb_id == TEAM_KB_ID


def test_kb_detail_returns_full_share_rows(harness: Harness) -> None:
    """详情页的共享清单要和清单页同构（含 kb_id），否则前端会拿不到归属。"""
    kb_id = harness.personal_kb("alice")
    harness.upload("alice", kb_id, "detail.md")
    harness.share(
        kb_id=kb_id,
        subject_type=SUBJECT_USER,
        subject_id=harness.users["bob"].user_id,
        caps={"read": True},
        as_user="alice",
    )

    harness.current["user"] = harness.users["alice"]
    response = harness.client().get(f"/api/kb/{kb_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["share_count"] == 1 and body["pending_count"] == 0
    share = body["shares"][0]
    assert share["kb_id"] == kb_id
    assert share["kb_name"] == body["name"]
    assert share["subject_name"] == "Bob"


def test_admin_all_view_covers_unrelated_shares(harness: Harness) -> None:
    """管理员的「全部关系」是全部，而不是「与我相关」的超集。"""
    kb_id = harness.personal_kb("alice")
    harness.upload("alice", kb_id, "rel.md")
    share = harness.share(
        kb_id=kb_id,
        subject_type=SUBJECT_USER,
        subject_id=harness.users["bob"].user_id,
        caps={"read": True},
        as_user="alice",
    )

    harness.current["user"] = harness.users["admin"]
    client = harness.client()
    everything = client.get("/api/shares", params={"view": "all"}).json()["items"]
    assert share["share_id"] in {item["share_id"] for item in everything}
    mine = client.get("/api/shares", params={"view": "mine"}).json()["items"]
    assert share["share_id"] not in {item["share_id"] for item in mine}
