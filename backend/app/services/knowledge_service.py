"""知识库管理：库本身、共享提案与审批、共享关系图。

权限判定全部委托给 :mod:`app.services.access`（能力并集），本模块只处理
「谁可以发起 / 谁可以审批 / 数据怎么组织成前端要的形状」这些业务流程。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.memory.groups import GroupRepository
from app.memory.knowledge import (
    KB_KIND_PERSONAL,
    KB_KIND_TEAM,
    SHARE_ACTIVE,
    SHARE_PENDING,
    SHARE_REJECTED,
    SUBJECT_GROUP,
    SUBJECT_TEAM,
    SUBJECT_TEAM_ID,
    SUBJECT_USER,
    KbRecord,
    KnowledgeRepository,
    ShareRecord,
)
from app.memory.users import UserRecord, UserRepository
from app.services.access import (
    ALL,
    NONE,
    TEAM_KB_ID,
    TEAM_KB_NAME,
    Access,
    AccessService,
    Caps,
)

logger = get_logger(__name__)


class KnowledgeError(Exception):
    """知识库业务错误（带 HTTP 语义的状态码）。"""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class KbView:
    """一个知识库对某个成员的样子（元数据 + 我的能力 + 规模）。"""

    kb: KbRecord
    my_caps: Caps
    document_count: int
    owner_name: str
    share_count: int
    pending_count: int
    can_manage: bool


class KnowledgeService:
    """知识库、共享与审批。"""

    def __init__(
        self,
        knowledge: KnowledgeRepository,
        groups: GroupRepository,
        users: UserRepository,
        documents_provider: Callable[[], object],
    ) -> None:
        self._knowledge = knowledge
        self._groups = groups
        self._users = users
        self._documents_provider = documents_provider
        self._access = AccessService(knowledge, groups)

    # ---------- 基础 ----------

    def access_for(self, user: UserRecord) -> Access:
        return self._access.resolve(user.user_id, user.is_admin)

    def _documents(self):
        return self._documents_provider()

    async def _document_rows(self) -> list[dict[str, object]]:
        """文档清单（不含权限过滤），用 dict 形式方便按 kb_id 聚合。"""
        items = await self._documents().list_documents()  # type: ignore[attr-defined]
        return [item.model_dump() for item in items]

    def get_kb(self, kb_id: str) -> KbRecord:
        record = self._knowledge.get(kb_id)
        if record is None:
            raise KnowledgeError("知识库不存在", status=404)
        return record

    def display_names(self) -> dict[str, str]:
        return {
            user.user_id: (user.display_name or user.username or user.user_id)
            for user in self._users.list_all()
        }

    # ---------- 启动引导 ----------

    async def bootstrap(self) -> None:
        """确保团队知识库存在，并把历史文档归位（幂等）。"""
        team = self._knowledge.get(TEAM_KB_ID)
        if team is None:
            owner = self._first_admin_id()
            team = self._knowledge.create(
                kb_id=TEAM_KB_ID,
                name=TEAM_KB_NAME,
                description="全团队共享的公共知识库，由管理员维护",
                owner_id=owner,
                kind=KB_KIND_TEAM,
                created_at=_now(),
            )
            logger.info(
                "已创建团队知识库",
                extra={"event": "kb_team_created", "status": "ok", "node": team.kb_id},
            )
        # 全员只读：可检索、可看列表、可看原文；写入仍归库主
        if not self._knowledge.find_share(
            kb_id=team.kb_id,
            subject_type=SUBJECT_TEAM,
            subject_id=SUBJECT_TEAM_ID,
            document_ids=(),
        ):
            self._knowledge.create_share(
                kb_id=team.kb_id,
                subject_type=SUBJECT_TEAM,
                subject_id=SUBJECT_TEAM_ID,
                can_search=True,
                can_list=True,
                can_read=True,
                can_write=False,
                requested_by=team.owner_id,
                status=SHARE_ACTIVE,
                reason="团队知识库默认全团队可读",
                created_at=_now(),
            )
        await self._migrate_legacy_documents()

    def _first_admin_id(self) -> str:
        admins = [user for user in self._users.list_all() if user.is_admin]
        return admins[0].user_id if admins else "local-user"

    async def _migrate_legacy_documents(self) -> None:
        """旧文档没有 kb_id：team 归入团队库，private 归入上传者的个人库。

        只处理缺少 ``kb_id`` 的文档，因此重启多次也不会重复迁移（幂等）。
        """
        documents = self._documents()
        # 迁移要看库里的原始元数据（visibility 已不在对外的 DocumentInfo 上）
        items = await documents.raw_documents()  # type: ignore[attr-defined]
        names = self.display_names()
        moved = 0
        for item in items:
            if item.get("kb_id"):
                continue
            document_id = str(item["document_id"])
            owner_id = item.get("owner_id")
            if (item.get("visibility") or "team") == "private" and owner_id:
                kb_id = self._personal_kb_for(str(owner_id), names)
            else:
                kb_id = TEAM_KB_ID
            await documents.assign_kb(document_id, kb_id)  # type: ignore[attr-defined]
            moved += 1
        if moved:
            logger.info(
                f"已把 {moved} 篇历史文档归入知识库",
                extra={"event": "kb_documents_migrated", "status": "ok", "node": str(moved)},
            )

    def _personal_kb_for(self, user_id: str, names: dict[str, str] | None = None) -> str:
        """取（必要时创建）某成员的个人知识库。"""
        for kb in self._knowledge.list_all():
            if kb.kind == KB_KIND_PERSONAL and kb.owner_id == user_id:
                return kb.kb_id
        display = (names or self.display_names()).get(user_id, user_id)
        base = f"{display} 的知识库"
        name = base
        index = 2
        while self._knowledge.get_by_name(name) is not None:
            name = f"{base}（{index}）"
            index += 1
        created = self._knowledge.create(
            name=name,
            description="个人知识库：默认只有自己可见，可申请共享给分组",
            owner_id=user_id,
            kind=KB_KIND_PERSONAL,
            created_at=_now(),
        )
        return created.kb_id

    async def ensure_personal_kb(self, user: UserRecord) -> KbRecord:
        for kb in self._knowledge.list_all():
            if kb.kind == KB_KIND_PERSONAL and kb.owner_id == user.user_id:
                return kb
        return self.get_kb(self._personal_kb_for(user.user_id))

    # ---------- 列表 ----------

    async def list_kbs(self, user: UserRecord) -> list[KbView]:
        """成员可见的知识库：能力非空或自己是库主；系统管理员可见全部元数据。"""
        access = self.access_for(user)
        counts = await self._document_counts_by_kb()
        names = self.display_names()
        shares_by_kb: dict[str, list[ShareRecord]] = {}
        for share in self._knowledge.list_all_shares():
            shares_by_kb.setdefault(share.kb_id, []).append(share)

        views: list[KbView] = []
        for kb in self._knowledge.list_all():
            caps = access.kb_caps(kb.kb_id)
            if not user.is_admin and caps.is_empty and kb.owner_id != user.user_id:
                continue
            shares = shares_by_kb.get(kb.kb_id, [])
            views.append(
                KbView(
                    kb=kb,
                    my_caps=caps,
                    document_count=counts.get(kb.kb_id, 0),
                    owner_name=names.get(kb.owner_id, kb.owner_id),
                    share_count=len([item for item in shares if item.is_active]),
                    pending_count=len([item for item in shares if item.is_pending]),
                    can_manage=access.manage_kb(kb.kb_id),
                )
            )
        # 自己参与度高的排在前面：有权限 > 库主 > 仅元数据
        views.sort(key=lambda view: (view.kb.kind != KB_KIND_TEAM, not view.my_caps.write))
        return views

    async def _document_counts_by_kb(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in await self._document_rows():
            kb_id = str(item.get("kb_id") or TEAM_KB_ID)
            counts[kb_id] = counts.get(kb_id, 0) + 1
        return counts

    async def kb_detail(self, kb_id: str, user: UserRecord) -> dict[str, object]:
        """单个知识库的详情：元数据 + 我的能力 + 共享清单（含待审批）。"""
        kb = self.get_kb(kb_id)
        access = self.access_for(user)
        caps = access.kb_caps(kb_id)
        if not user.is_admin and caps.is_empty and kb.owner_id != user.user_id:
            raise KnowledgeError("知识库不存在或你无权访问", status=404)
        names = self.display_names()
        group_names = {group.group_id: group.name for group in self._groups.list_all()}
        kb_names = {item.kb_id: item.name for item in self._knowledge.list_all()}
        rows = self._knowledge.list_shares_for_kb(kb_id)
        shares = [
            self._share_row(share, names=names, kb_names=kb_names, group_names=group_names)
            for share in rows
        ]
        counts = await self._document_counts_by_kb()
        return {
            "kb_id": kb.kb_id,
            "name": kb.name,
            "description": kb.description,
            "kind": kb.kind,
            "owner_id": kb.owner_id,
            "owner_name": names.get(kb.owner_id, kb.owner_id),
            "document_count": counts.get(kb_id, 0),
            "share_count": len([item for item in rows if item.is_active]),
            "pending_count": len([item for item in rows if item.is_pending]),
            "created_at": kb.created_at,
            "updated_at": kb.updated_at,
            "my_caps": caps.as_dict(),
            "my_caps_label": caps.describe(),
            "can_manage": access.manage_kb(kb_id),
            "shares": shares,
        }

    def _share_row(
        self,
        share: ShareRecord,
        *,
        names: dict[str, str],
        kb_names: dict[str, str],
        group_names: dict[str, str],
    ) -> dict[str, object]:
        """一条共享的统一序列化：详情页、清单页、审批都返回同构的结构。"""
        caps = Caps.from_share(share)
        return {
            "share_id": share.share_id,
            "kb_id": share.kb_id,
            "kb_name": kb_names.get(share.kb_id, share.kb_id),
            "subject_type": share.subject_type,
            "subject_id": share.subject_id,
            "subject_name": self._subject_name(share, names, group_names),
            "caps": caps.as_dict(),
            "caps_label": caps.describe(),
            "document_ids": list(share.document_ids),
            "status": share.status,
            "reason": share.reason,
            "requested_by": share.requested_by,
            "requested_by_name": names.get(share.requested_by, share.requested_by),
            "decided_by": share.decided_by,
            "decided_at": share.decided_at,
            "decision_note": share.decision_note,
            "created_at": share.created_at,
        }

    @staticmethod
    def _subject_name(share: ShareRecord, names: dict[str, str], groups: dict[str, str]) -> str:
        if share.subject_type == SUBJECT_TEAM:
            return "全团队"
        if share.subject_type == SUBJECT_GROUP:
            return groups.get(share.subject_id, share.subject_id)
        return names.get(share.subject_id, share.subject_id)

    # ---------- 创建 / 修改 / 删除 ----------

    async def create_kb(
        self, *, name: str, description: str, user: UserRecord, kind: str = KB_KIND_PERSONAL
    ) -> KbRecord:
        clean = name.strip()
        if not clean:
            raise KnowledgeError("知识库名称不能为空", status=422)
        if len(clean) > 40:
            raise KnowledgeError("知识库名称最多 40 个字", status=422)
        if self._knowledge.get_by_name(clean) is not None:
            raise KnowledgeError("已有同名知识库", status=409)
        if kind not in (KB_KIND_PERSONAL, KB_KIND_TEAM):
            raise KnowledgeError("不支持的知识库类型", status=422)
        if kind == KB_KIND_TEAM and not user.is_admin:
            raise KnowledgeError("只有管理员可以创建团队知识库", status=403)
        return self._knowledge.create(
            name=clean,
            description=description.strip(),
            owner_id=user.user_id,
            kind=kind,
            created_at=_now(),
        )

    async def update_kb(
        self, kb_id: str, *, name: str | None, description: str | None, user: UserRecord
    ) -> KbRecord:
        kb = self.get_kb(kb_id)
        if not self.access_for(user).manage_kb(kb_id):
            raise KnowledgeError("只有知识库管理员可以修改", status=403)
        if name is not None:
            clean = name.strip()
            if not clean:
                raise KnowledgeError("知识库名称不能为空", status=422)
            existing = self._knowledge.get_by_name(clean)
            if existing is not None and existing.kb_id != kb_id:
                raise KnowledgeError("已有同名知识库", status=409)
            name = clean
        self._knowledge.update(kb_id, name=name, description=description, updated_at=_now())
        return self.get_kb(kb.kb_id)

    async def delete_kb(self, kb_id: str, *, user: UserRecord) -> int:
        """删除知识库及其文档；团队的公共库不允许删除。"""
        kb = self.get_kb(kb_id)
        if kb.kind == KB_KIND_TEAM:
            raise KnowledgeError("团队知识库不可删除", status=409)
        if not self.access_for(user).manage_kb(kb_id):
            raise KnowledgeError("只有知识库管理员可以删除", status=403)
        documents = self._documents()
        removed = 0
        for item in await self._document_rows():
            if str(item.get("kb_id") or TEAM_KB_ID) == kb_id:
                await documents.delete_document(item["document_id"], user_id=None)  # type: ignore[attr-defined]
                removed += 1
        self._knowledge.delete(kb_id)
        return removed

    # ---------- 共享 ----------

    async def create_share(
        self,
        kb_id: str,
        *,
        subject_type: str,
        subject_id: str,
        caps: Caps,
        document_ids: list[str] | None,
        reason: str,
        user: UserRecord,
    ) -> ShareRecord:
        """创建共享：库主 / 管理员直接生效，其他成员发起的是「待审批」提案。"""
        self.get_kb(kb_id)
        access = self.access_for(user)
        my_caps = access.kb_caps(kb_id)
        # 库主 / 管理员直接生效；能读到这个库的成员可以提案（等管理员审批）；
        # 完全看不到这个库的人不能发起共享
        if not (access.manage_kb(kb_id) or my_caps.read):
            raise KnowledgeError("只有知识库管理员或可见成员可以发起共享", status=403)

        normalized = Caps.of(search=caps.search, list=caps.list, read=caps.read, write=caps.write)
        if normalized.is_empty:
            raise KnowledgeError("至少要授予一项能力", status=422)

        self._validate_subject(subject_type, subject_id)
        subset = await self._validate_documents(kb_id, document_ids)

        # 库主 / 系统管理员直接生效；其他被授权的管理者走审批
        direct = access.is_owner(kb_id) or user.is_admin
        status = SHARE_ACTIVE if direct else SHARE_PENDING

        existing = self._knowledge.find_share(
            kb_id=kb_id,
            subject_type=subject_type,
            subject_id=subject_id,
            document_ids=subset,
        )
        if existing is not None:
            if existing.status == SHARE_ACTIVE and direct:
                # 已有生效的同一共享：直接调整能力，不产生重复记录
                self._knowledge.update_share_permissions(
                    existing.share_id,
                    can_search=normalized.search,
                    can_list=normalized.list,
                    can_read=normalized.read,
                    can_write=normalized.write,
                )
                refreshed = self._knowledge.get_share(existing.share_id)
                assert refreshed is not None
                return refreshed
            if existing.status == SHARE_PENDING:
                raise KnowledgeError("这条共享已在等待审批", status=409)
            if existing.status == SHARE_REJECTED:
                self._knowledge.update_share_permissions(
                    existing.share_id,
                    can_search=normalized.search,
                    can_list=normalized.list,
                    can_read=normalized.read,
                    can_write=normalized.write,
                    status=SHARE_PENDING,
                )
                return self._knowledge.get_share(existing.share_id) or existing

        return self._knowledge.create_share(
            kb_id=kb_id,
            subject_type=subject_type,
            subject_id=subject_id,
            can_search=normalized.search,
            can_list=normalized.list,
            can_read=normalized.read,
            can_write=normalized.write,
            requested_by=user.user_id,
            status=status,
            document_ids=subset,
            reason=reason.strip(),
            created_at=_now(),
        )

    def _validate_subject(self, subject_type: str, subject_id: str) -> None:
        if subject_type == SUBJECT_TEAM:
            return
        if subject_type == SUBJECT_USER:
            if self._users.get_by_id(subject_id) is None:
                raise KnowledgeError("成员不存在", status=404)
            return
        if subject_type == SUBJECT_GROUP:
            if self._groups.get(subject_id) is None:
                raise KnowledgeError("分组不存在", status=404)
            return
        raise KnowledgeError("共享主体只能是成员、分组或全团队", status=422)

    async def _validate_documents(
        self, kb_id: str, document_ids: list[str] | None
    ) -> tuple[str, ...]:
        """共享可以是整库，也可以是其中若干文件；文件必须属于该库。"""
        wanted = tuple(dict.fromkeys(str(item) for item in (document_ids or []) if item))
        if not wanted:
            return ()
        owned = {
            str(item["document_id"])
            for item in await self._document_rows()
            if str(item.get("kb_id") or TEAM_KB_ID) == kb_id
        }
        missing = [item for item in wanted if item not in owned]
        if missing:
            raise KnowledgeError(f"{len(missing)} 个文件不属于该知识库", status=422)
        return wanted

    async def decide_share(
        self, share_id: str, *, approve: bool, note: str, user: UserRecord
    ) -> ShareRecord:
        share = self._knowledge.get_share(share_id)
        if share is None:
            raise KnowledgeError("共享记录不存在", status=404)
        if not share.is_pending:
            raise KnowledgeError("该共享已经处理过了", status=409)
        if not user.is_admin:
            raise KnowledgeError("需要管理员审批", status=403)
        self._knowledge.decide_share(
            share_id,
            status=SHARE_ACTIVE if approve else SHARE_REJECTED,
            decided_by=user.user_id,
            decided_at=_now(),
            note=note.strip(),
        )
        refreshed = self._knowledge.get_share(share_id)
        assert refreshed is not None
        return refreshed

    async def revoke_share(self, share_id: str, *, user: UserRecord) -> None:
        share = self._knowledge.get_share(share_id)
        if share is None:
            raise KnowledgeError("共享记录不存在", status=404)
        if not self.access_for(user).manage_kb(share.kb_id):
            raise KnowledgeError("只有知识库管理员可以撤销共享", status=403)
        self._knowledge.delete_share(share_id)

    async def shares_for_user(self, user: UserRecord) -> list[dict[str, object]]:
        """「与我相关」的共享：我发起的、共享给我的（含所在分组）、待我审批的。"""
        names = self.display_names()
        kb_names = {kb.kb_id: kb.name for kb in self._knowledge.list_all()}
        group_names = {group.group_id: group.name for group in self._groups.list_all()}
        my_groups = set(self._groups.group_ids_for_user(user.user_id))
        rows: list[dict[str, object]] = []
        for share in self._knowledge.list_all_shares():
            related = (
                share.requested_by == user.user_id
                or (share.subject_type == SUBJECT_USER and share.subject_id == user.user_id)
                or (share.subject_type == SUBJECT_GROUP and share.subject_id in my_groups)
                or (share.is_pending and user.is_admin)
            )
            if not related:
                continue
            rows.append(
                self._share_row(share, names=names, kb_names=kb_names, group_names=group_names)
            )
        return rows

    async def all_shares(self, user: UserRecord) -> list[dict[str, object]]:
        """全部共享关系（管理员视角看关系不看内容）；非管理员退化为「与我相关」。"""
        if not user.is_admin:
            return await self.shares_for_user(user)
        names = self.display_names()
        kb_names = {kb.kb_id: kb.name for kb in self._knowledge.list_all()}
        group_names = {group.group_id: group.name for group in self._groups.list_all()}
        return [
            self._share_row(share, names=names, kb_names=kb_names, group_names=group_names)
            for share in self._knowledge.list_all_shares()
        ]

    # ---------- 共享关系图 ----------

    async def graph(self, user: UserRecord) -> dict[str, object]:
        """人 / 组 / 知识库 的共享关系图。

        管理员看到全部「关系」，但仍然拿不到库内容（内容权限只由能力并集决定）；
        普通成员只看到与自己相关的部分，避免泄露别人的协作关系。
        """
        access = self.access_for(user)
        names = self.display_names()
        groups = self._groups.list_all()
        group_members = {
            group.group_id: [
                member
                for member in self._groups.list_members(group.group_id)
                if member.status == "active"
            ]
            for group in groups
        }
        shares = self._knowledge.list_all_shares()
        counts = await self._document_counts_by_kb()

        visible_kb_ids: set[str] = set()
        if user.is_admin:
            visible_kb_ids = {kb.kb_id for kb in self._knowledge.list_all()}
        else:
            my_groups = set(self._groups.group_ids_for_user(user.user_id))
            for kb in self._knowledge.list_all():
                caps = access.kb_caps(kb.kb_id)
                if not caps.is_empty or kb.owner_id == user.user_id:
                    visible_kb_ids.add(kb.kb_id)
            for share in shares:
                mine = (
                    share.requested_by == user.user_id
                    or (share.subject_type == SUBJECT_USER and share.subject_id == user.user_id)
                    or (share.subject_type == SUBJECT_GROUP and share.subject_id in my_groups)
                )
                if mine:
                    visible_kb_ids.add(share.kb_id)

        nodes: dict[str, dict[str, object]] = {}
        for user_id, display in names.items():
            if not user.is_admin and user_id != user.user_id:
                continue
            nodes[f"user:{user_id}"] = {
                "id": f"user:{user_id}",
                "type": "user",
                "label": display,
                "is_me": user_id == user.user_id,
            }

        member_edges: list[dict[str, object]] = []
        used_groups = {
            share.subject_id
            for share in shares
            if share.subject_type == SUBJECT_GROUP and share.kb_id in visible_kb_ids
        }
        my_groups = set(self._groups.group_ids_for_user(user.user_id))
        if not user.is_admin:
            used_groups |= my_groups
        for group in groups:
            if group.group_id not in used_groups:
                continue
            members = group_members.get(group.group_id, [])
            nodes[f"group:{group.group_id}"] = {
                "id": f"group:{group.group_id}",
                "type": "group",
                "label": group.name,
                "member_count": len(members),
            }
            # 成员与组的连线：管理员看全部，成员只看自己在的那个组
            for member in members:
                if not user.is_admin and member.user_id != user.user_id:
                    continue
                source = f"user:{member.user_id}"
                if source not in nodes:
                    continue
                member_edges.append(
                    {
                        "id": f"member:{group.group_id}:{member.user_id}",
                        "source": source,
                        "target": f"group:{group.group_id}",
                        "kind": "member",
                        "status": "active",
                        "label": "成员",
                    }
                )

        for kb in self._knowledge.list_all():
            if kb.kb_id not in visible_kb_ids:
                continue
            nodes[f"kb:{kb.kb_id}"] = {
                "id": f"kb:{kb.kb_id}",
                "type": "kb",
                "label": kb.name,
                "kind": kb.kind,
                "owner_name": names.get(kb.owner_id, kb.owner_id),
                "document_count": counts.get(kb.kb_id, 0),
                "my_caps": access.kb_caps(kb.kb_id).as_dict(),
            }

        share_edges: list[dict[str, object]] = []
        for share in shares:
            if share.kb_id not in visible_kb_ids:
                continue
            if share.subject_type == SUBJECT_TEAM:
                source = "team:*"
            elif share.subject_type == SUBJECT_GROUP:
                source = f"group:{share.subject_id}"
            else:
                source = f"user:{share.subject_id}"
            if source.startswith("user:") and source not in nodes:
                continue
            if source.startswith("group:") and source not in nodes:
                continue
            share_edges.append(
                {
                    "id": share.share_id,
                    "source": source,
                    "target": f"kb:{share.kb_id}",
                    "kind": "share",
                    "status": share.status,
                    "caps": Caps.from_share(share).as_dict(),
                    "label": Caps.from_share(share).describe(),
                    "document_ids": list(share.document_ids),
                    "requested_by_name": names.get(share.requested_by, share.requested_by),
                }
            )

        if any(edge["source"] == "team:*" for edge in share_edges):
            nodes["team:*"] = {
                "id": "team:*",
                "type": "team",
                "label": "全团队",
                "member_count": len(names),
            }

        return {
            "nodes": list(nodes.values()),
            "edges": member_edges + share_edges,
            "pending_count": sum(1 for share in shares if share.is_pending and user.is_admin),
        }

    # ---------- 供文档服务使用 ----------

    def caps_for_kb(self, kb_id: str, user: UserRecord) -> Caps:
        return self.access_for(user).kb_caps(kb_id)

    def owner_kb(self, kb_id: str) -> str | None:
        kb = self._knowledge.get(kb_id)
        return kb.owner_id if kb else None

    def empty_caps(self) -> Caps:
        return NONE

    def full_caps(self) -> Caps:
        return ALL
