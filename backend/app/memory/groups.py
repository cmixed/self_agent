"""团队分组仓储。

分组是「一批人」的载体：共享可以授予某个分组，因此组的成员变更会直接改变
谁能访问哪些知识库——这正是组合式权限（共享关系可叠加、可撤销）的好处。
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from app.memory.sqlite import SqliteDatabase

ROLE_GROUP_MANAGER = "manager"
ROLE_GROUP_MEMBER = "member"
GROUP_ROLES = (ROLE_GROUP_MANAGER, ROLE_GROUP_MEMBER)

MEMBER_ACTIVE = "active"
MEMBER_PENDING = "pending"
MEMBER_STATUSES = (MEMBER_ACTIVE, MEMBER_PENDING)


@dataclass(frozen=True)
class GroupRecord:
    group_id: str
    name: str
    description: str
    created_by: str
    created_at: str


@dataclass(frozen=True)
class GroupMemberRecord:
    group_id: str
    user_id: str
    role: str
    status: str
    added_by: str
    joined_at: str

    @property
    def is_manager(self) -> bool:
        return self.role == ROLE_GROUP_MANAGER

    @property
    def is_active(self) -> bool:
        return self.status == MEMBER_ACTIVE


def _row_to_group(row: sqlite3.Row | None) -> GroupRecord | None:
    if row is None:
        return None
    return GroupRecord(
        group_id=str(row["group_id"]),
        name=str(row["name"]),
        description=str(row["description"] or ""),
        created_by=str(row["created_by"]),
        created_at=str(row["created_at"]),
    )


def _row_to_member(row: sqlite3.Row | None) -> GroupMemberRecord | None:
    if row is None:
        return None
    return GroupMemberRecord(
        group_id=str(row["group_id"]),
        user_id=str(row["user_id"]),
        role=str(row["role"] or ROLE_GROUP_MEMBER),
        status=str(row["status"] or MEMBER_ACTIVE),
        added_by=str(row["added_by"] or ""),
        joined_at=str(row["joined_at"]),
    )


def new_group_id() -> str:
    return f"grp-{uuid.uuid4().hex[:12]}"


class GroupRepository:
    """分组与分组成员的持久化操作。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    # ---------- 分组 ----------

    def get(self, group_id: str) -> GroupRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM team_groups WHERE group_id = ?", (group_id,)
            ).fetchone()
        return _row_to_group(row)

    def get_by_name(self, name: str) -> GroupRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM team_groups WHERE lower(name) = lower(?)", (name.strip(),)
            ).fetchone()
        return _row_to_group(row)

    def list_all(self) -> list[GroupRecord]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT * FROM team_groups ORDER BY name ASC").fetchall()
        return [group for group in (_row_to_group(row) for row in rows) if group]

    def create(
        self,
        *,
        name: str,
        created_by: str,
        description: str = "",
        created_at: str,
        group_id: str | None = None,
    ) -> GroupRecord:
        resolved_id = group_id or new_group_id()
        with self._database.connect() as connection:
            connection.execute(
                "INSERT INTO team_groups (group_id, name, description, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (resolved_id, name, description, created_by, created_at),
            )
            connection.commit()
        record = self.get(resolved_id)
        assert record is not None
        return record

    def update(self, group_id: str, *, name: str, description: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE team_groups SET name = ?, description = ? WHERE group_id = ?",
                (name, description, group_id),
            )
            connection.commit()

    def delete(self, group_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute("DELETE FROM team_groups WHERE group_id = ?", (group_id,))
            connection.commit()

    # ---------- 成员 ----------

    def list_members(self, group_id: str) -> list[GroupMemberRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM team_group_members WHERE group_id = ? "
                "ORDER BY status ASC, joined_at ASC",
                (group_id,),
            ).fetchall()
        return [member for member in (_row_to_member(row) for row in rows) if member]

    def get_member(self, group_id: str, user_id: str) -> GroupMemberRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM team_group_members WHERE group_id = ? AND user_id = ?",
                (group_id, user_id),
            ).fetchone()
        return _row_to_member(row)

    def group_ids_for_user(self, user_id: str, *, status: str = MEMBER_ACTIVE) -> list[str]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT group_id FROM team_group_members WHERE user_id = ? AND status = ?",
                (user_id, status),
            ).fetchall()
        return [str(row["group_id"]) for row in rows]

    def memberships_for_user(self, user_id: str) -> list[GroupMemberRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM team_group_members WHERE user_id = ? ORDER BY joined_at ASC",
                (user_id,),
            ).fetchall()
        return [member for member in (_row_to_member(row) for row in rows) if member]

    def upsert_member(
        self,
        *,
        group_id: str,
        user_id: str,
        role: str = ROLE_GROUP_MEMBER,
        status: str = MEMBER_ACTIVE,
        added_by: str = "",
        joined_at: str,
    ) -> GroupMemberRecord:
        with self._database.connect() as connection:
            connection.execute(
                "INSERT INTO team_group_members "
                "(group_id, user_id, role, status, added_by, joined_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(group_id, user_id) DO UPDATE SET "
                "role = excluded.role, status = excluded.status, "
                "added_by = excluded.added_by, joined_at = excluded.joined_at",
                (group_id, user_id, role, status, added_by, joined_at),
            )
            connection.commit()
        record = self.get_member(group_id, user_id)
        assert record is not None
        return record

    def set_member_role(self, group_id: str, user_id: str, role: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE team_group_members SET role = ? WHERE group_id = ? AND user_id = ?",
                (role, group_id, user_id),
            )
            connection.commit()

    def remove_member(self, group_id: str, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "DELETE FROM team_group_members WHERE group_id = ? AND user_id = ?",
                (group_id, user_id),
            )
            connection.commit()

    def count_active_members(self, group_id: str) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM team_group_members WHERE group_id = ? AND status = ?",
                (group_id, MEMBER_ACTIVE),
            ).fetchone()
        return int(row["n"]) if row else 0

    def list_pending_requests(self) -> list[GroupMemberRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM team_group_members WHERE status = ? ORDER BY joined_at ASC",
                (MEMBER_PENDING,),
            ).fetchall()
        return [member for member in (_row_to_member(row) for row in rows) if member]
