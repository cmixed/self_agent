"""分组管理：建组、拉人、申请加入、组内审批。

入组规则（按需求）：
- 管理员可以直接建组、直接拉人（立即生效）；
- 组内「编辑者」（manager）可以批准他人加入，这是默认审批路径；
- 普通成员只能提交加入申请，等编辑者或管理员处理。
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.groups import (
    MEMBER_ACTIVE,
    MEMBER_PENDING,
    ROLE_GROUP_MANAGER,
    ROLE_GROUP_MEMBER,
    GroupMemberRecord,
    GroupRecord,
    GroupRepository,
)
from app.memory.knowledge import SUBJECT_GROUP, KnowledgeRepository
from app.memory.users import UserRecord, UserRepository


class GroupError(Exception):
    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _now() -> str:
    return datetime.now(UTC).isoformat()


class GroupService:
    def __init__(
        self,
        groups: GroupRepository,
        users: UserRepository,
        knowledge: KnowledgeRepository,
    ) -> None:
        self._groups = groups
        self._users = users
        self._knowledge = knowledge

    def names(self) -> dict[str, str]:
        return {
            user.user_id: (user.display_name or user.username or user.user_id)
            for user in self._users.list_all()
        }

    def get(self, group_id: str) -> GroupRecord:
        record = self._groups.get(group_id)
        if record is None:
            raise GroupError("分组不存在", status=404)
        return record

    def _can_manage(self, group_id: str, user: UserRecord) -> bool:
        if user.is_admin:
            return True
        member = self._groups.get_member(group_id, user.user_id)
        return bool(member and member.is_active and member.is_manager)

    def list_groups(self, user: UserRecord) -> list[dict[str, object]]:
        """管理员看全部；成员看自己所在的组 + 可以申请加入的组。"""
        names = self.names()
        rows: list[dict[str, object]] = []
        for group in self._groups.list_all():
            members = self._groups.list_members(group.group_id)
            mine = next((item for item in members if item.user_id == user.user_id), None)
            if not user.is_admin and mine is None:
                # 不是管理员也不在组里：仍然可见（方便申请加入），但看不到成员名单
                rows.append(
                    {
                        "group_id": group.group_id,
                        "name": group.name,
                        "description": group.description,
                        "created_by": group.created_by,
                        "created_by_name": names.get(group.created_by, group.created_by),
                        "member_count": len([m for m in members if m.is_active]),
                        "pending_count": len([m for m in members if m.status == MEMBER_PENDING]),
                        "my_role": None,
                        "can_manage": False,
                        "members": [],
                    }
                )
                continue
            rows.append(self._group_payload(group, members, user, names))
        return rows

    def _group_payload(
        self,
        group: GroupRecord,
        members: list[GroupMemberRecord],
        user: UserRecord,
        names: dict[str, str],
    ) -> dict[str, object]:
        mine = next((item for item in members if item.user_id == user.user_id), None)
        can_manage = self._can_manage(group.group_id, user)
        visible_members = members if (can_manage or user.is_admin or mine) else []
        return {
            "group_id": group.group_id,
            "name": group.name,
            "description": group.description,
            "created_by": group.created_by,
            "created_by_name": names.get(group.created_by, group.created_by),
            "member_count": len([m for m in members if m.is_active]),
            "pending_count": len([m for m in members if m.status == MEMBER_PENDING]),
            "my_role": (mine.role if mine and mine.is_active else ("pending" if mine else None)),
            "can_manage": can_manage,
            "members": [
                {
                    "user_id": member.user_id,
                    "display_name": names.get(member.user_id, member.user_id),
                    "role": member.role,
                    "status": member.status,
                    "added_by": member.added_by,
                    "joined_at": member.joined_at,
                }
                for member in visible_members
            ],
        }

    def create(self, *, name: str, description: str, user: UserRecord) -> GroupRecord:
        clean = name.strip()
        if not clean:
            raise GroupError("分组名称不能为空", status=422)
        if self._groups.get_by_name(clean) is not None:
            raise GroupError("已有同名分组", status=409)
        group = self._groups.create(
            name=clean, description=description.strip(), created_by=user.user_id, created_at=_now()
        )
        # 建组人自动成为组内编辑者
        self._groups.upsert_member(
            group_id=group.group_id,
            user_id=user.user_id,
            role=ROLE_GROUP_MANAGER,
            status=MEMBER_ACTIVE,
            added_by=user.user_id,
            joined_at=_now(),
        )
        return group

    def update(
        self, group_id: str, *, name: str | None, description: str | None, user: UserRecord
    ) -> GroupRecord:
        group = self.get(group_id)
        if not self._can_manage(group_id, user):
            raise GroupError("只有组内编辑者或管理员可以修改分组", status=403)
        if name is not None:
            clean = name.strip()
            if not clean:
                raise GroupError("分组名称不能为空", status=422)
            existing = self._groups.get_by_name(clean)
            if existing is not None and existing.group_id != group_id:
                raise GroupError("已有同名分组", status=409)
        self._groups.update(
            group_id,
            name=name.strip() if name is not None else group.name,
            description=description.strip() if description is not None else group.description,
        )
        return self.get(group_id)

    def delete(self, group_id: str, *, user: UserRecord) -> None:
        self.get(group_id)
        if not self._can_manage(group_id, user):
            raise GroupError("只有组内编辑者或管理员可以删除分组", status=403)
        # 组没了，指向它的共享也一并清理（否则权限来源会悬空）
        self._knowledge.delete_shares_for_subject(SUBJECT_GROUP, group_id)
        self._groups.delete(group_id)

    def add_member(
        self, group_id: str, *, user_id: str, role: str, actor: UserRecord
    ) -> GroupMemberRecord:
        self.get(group_id)
        if self._users.get_by_id(user_id) is None:
            raise GroupError("成员不存在", status=404)
        if role not in (ROLE_GROUP_MANAGER, ROLE_GROUP_MEMBER):
            raise GroupError("不支持的角色", status=422)
        if not self._can_manage(group_id, actor):
            raise GroupError("只有组内编辑者或管理员可以直接拉人", status=403)
        return self._groups.upsert_member(
            group_id=group_id,
            user_id=user_id,
            role=role,
            status=MEMBER_ACTIVE,
            added_by=actor.user_id,
            joined_at=_now(),
        )

    def request_join(self, group_id: str, *, actor: UserRecord) -> GroupMemberRecord:
        """成员自己申请加入：先进入 pending，等组内编辑者或管理员同意。"""
        self.get(group_id)
        existing = self._groups.get_member(group_id, actor.user_id)
        if existing is not None and existing.is_active:
            raise GroupError("你已在该分组中", status=409)
        if existing is not None and existing.status == MEMBER_PENDING:
            raise GroupError("申请已提交，等待审批", status=409)
        return self._groups.upsert_member(
            group_id=group_id,
            user_id=actor.user_id,
            role=ROLE_GROUP_MEMBER,
            status=MEMBER_PENDING,
            added_by=actor.user_id,
            joined_at=_now(),
        )

    def decide_member(
        self, group_id: str, *, user_id: str, approve: bool, actor: UserRecord
    ) -> None:
        self.get(group_id)
        member = self._groups.get_member(group_id, user_id)
        if member is None:
            raise GroupError("没有这条入组申请", status=404)
        if member.is_active:
            raise GroupError("该成员已在组内", status=409)
        if not self._can_manage(group_id, actor):
            raise GroupError("只有组内编辑者或管理员可以审批", status=403)
        if approve:
            self._groups.upsert_member(
                group_id=group_id,
                user_id=user_id,
                role=member.role,
                status=MEMBER_ACTIVE,
                added_by=actor.user_id,
                joined_at=_now(),
            )
        else:
            self._groups.remove_member(group_id, user_id)

    def remove_member(self, group_id: str, *, user_id: str, actor: UserRecord) -> None:
        self.get(group_id)
        if user_id != actor.user_id and not self._can_manage(group_id, actor):
            raise GroupError("只有组内编辑者或管理员可以移除成员", status=403)
        member = self._groups.get_member(group_id, user_id)
        if member is None:
            raise GroupError("该成员不在组内", status=404)
        # 不能把最后一个编辑者移除掉，否则这个组没人能审批
        if member.is_manager and self._groups.count_active_members(group_id) <= 1:
            raise GroupError("分组至少需要保留一位编辑者", status=409)
        self._groups.remove_member(group_id, user_id)

    def set_role(self, group_id: str, *, user_id: str, role: str, actor: UserRecord) -> None:
        self.get(group_id)
        if not self._can_manage(group_id, actor):
            raise GroupError("只有组内编辑者或管理员可以调整角色", status=403)
        if role not in (ROLE_GROUP_MANAGER, ROLE_GROUP_MEMBER):
            raise GroupError("不支持的角色", status=422)
        self._groups.set_member_role(group_id, user_id, role)

    def my_group_ids(self, user_id: str) -> list[str]:
        return self._groups.group_ids_for_user(user_id)
