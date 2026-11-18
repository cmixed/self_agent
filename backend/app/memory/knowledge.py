"""知识库与共享关系仓储。

表结构见 ``app/memory/sqlite.py``：``knowledge_bases`` / ``kb_shares``。
本模块只负责 SQL 与行映射；能力并集、审批规则等业务判断放在
``app/services/access.py`` 与 ``app/services/knowledge_service.py``。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.memory.sqlite import SqliteDatabase

# 知识库类型：团队公共库 / 个人库
KB_KIND_TEAM = "team"
KB_KIND_PERSONAL = "personal"
KB_KINDS = (KB_KIND_TEAM, KB_KIND_PERSONAL)

# 共享主体：指定成员 / 分组 / 全团队
SUBJECT_USER = "user"
SUBJECT_GROUP = "group"
SUBJECT_TEAM = "team"
SUBJECT_TYPES = (SUBJECT_USER, SUBJECT_GROUP, SUBJECT_TEAM)
SUBJECT_TEAM_ID = "*"

SHARE_PENDING = "pending"
SHARE_ACTIVE = "active"
SHARE_REJECTED = "rejected"
SHARE_STATUSES = (SHARE_PENDING, SHARE_ACTIVE, SHARE_REJECTED)


@dataclass(frozen=True)
class KbRecord:
    kb_id: str
    name: str
    description: str
    owner_id: str
    kind: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ShareRecord:
    share_id: str
    kb_id: str
    subject_type: str
    subject_id: str
    can_search: bool
    can_list: bool
    can_read: bool
    can_write: bool
    document_ids: tuple[str, ...]
    status: str
    requested_by: str
    reason: str
    decided_by: str | None
    decided_at: str | None
    decision_note: str
    created_at: str

    @property
    def is_active(self) -> bool:
        return self.status == SHARE_ACTIVE

    @property
    def is_pending(self) -> bool:
        return self.status == SHARE_PENDING


def _loads_documents(raw: Any) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        value = json.loads(str(raw))
    except TypeError, ValueError:
        return ()
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item)


def _row_to_kb(row: sqlite3.Row | None) -> KbRecord | None:
    if row is None:
        return None
    return KbRecord(
        kb_id=str(row["kb_id"]),
        name=str(row["name"]),
        description=str(row["description"] or ""),
        owner_id=str(row["owner_id"]),
        kind=str(row["kind"] or KB_KIND_PERSONAL),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _row_to_share(row: sqlite3.Row | None) -> ShareRecord | None:
    if row is None:
        return None
    return ShareRecord(
        share_id=str(row["share_id"]),
        kb_id=str(row["kb_id"]),
        subject_type=str(row["subject_type"]),
        subject_id=str(row["subject_id"]),
        can_search=bool(row["can_search"]),
        can_list=bool(row["can_list"]),
        can_read=bool(row["can_read"]),
        can_write=bool(row["can_write"]),
        document_ids=_loads_documents(row["document_ids"]),
        status=str(row["status"]),
        requested_by=str(row["requested_by"]),
        reason=str(row["reason"] or ""),
        decided_by=(row["decided_by"] if row["decided_by"] else None),
        decided_at=(row["decided_at"] if row["decided_at"] else None),
        decision_note=str(row["decision_note"] or ""),
        created_at=str(row["created_at"]),
    )


def new_kb_id() -> str:
    return f"kb-{uuid.uuid4().hex[:12]}"


def new_share_id() -> str:
    return f"shr-{uuid.uuid4().hex[:12]}"


class KnowledgeRepository:
    """知识库与共享关系的持久化操作。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    # ---------- 知识库 ----------

    def get(self, kb_id: str) -> KbRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_bases WHERE kb_id = ?", (kb_id,)
            ).fetchone()
        return _row_to_kb(row)

    def get_by_name(self, name: str) -> KbRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_bases WHERE lower(name) = lower(?)", (name.strip(),)
            ).fetchone()
        return _row_to_kb(row)

    def list_all(self) -> list[KbRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_bases ORDER BY created_at ASC"
            ).fetchall()
        return [kb for kb in (_row_to_kb(row) for row in rows) if kb]

    def create(
        self,
        *,
        name: str,
        owner_id: str,
        description: str = "",
        kind: str = KB_KIND_PERSONAL,
        kb_id: str | None = None,
        created_at: str,
    ) -> KbRecord:
        resolved_id = kb_id or new_kb_id()
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_bases
                    (kb_id, name, description, owner_id, kind, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (resolved_id, name, description, owner_id, kind, created_at, created_at),
            )
            connection.commit()
        record = self.get(resolved_id)
        assert record is not None
        return record

    def update(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        owner_id: str | None = None,
        updated_at: str,
    ) -> None:
        fields: list[str] = []
        params: list[object] = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if description is not None:
            fields.append("description = ?")
            params.append(description)
        if owner_id is not None:
            fields.append("owner_id = ?")
            params.append(owner_id)
        if not fields:
            return
        fields.append("updated_at = ?")
        params.append(updated_at)
        params.append(kb_id)
        with self._database.connect() as connection:
            connection.execute(
                f"UPDATE knowledge_bases SET {', '.join(fields)} WHERE kb_id = ?", params
            )
            connection.commit()

    def delete(self, kb_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute("DELETE FROM knowledge_bases WHERE kb_id = ?", (kb_id,))
            connection.commit()

    def count_owned(self, user_id: str) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM knowledge_bases WHERE owner_id = ?", (user_id,)
            ).fetchone()
        return int(row["n"]) if row else 0

    # ---------- 共享 ----------

    def get_share(self, share_id: str) -> ShareRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM kb_shares WHERE share_id = ?", (share_id,)
            ).fetchone()
        return _row_to_share(row)

    def list_shares_for_kb(self, kb_id: str) -> list[ShareRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kb_shares WHERE kb_id = ? ORDER BY created_at ASC", (kb_id,)
            ).fetchall()
        return [share for share in (_row_to_share(row) for row in rows) if share]

    def list_all_shares(self, *, status: str | None = None) -> list[ShareRecord]:
        sql = "SELECT * FROM kb_shares"
        params: list[object] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        with self._database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [share for share in (_row_to_share(row) for row in rows) if share]

    def list_active_for_subject(self, subject_type: str, subject_id: str) -> list[ShareRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kb_shares WHERE subject_type = ? AND subject_id = ? "
                "AND status = ? ORDER BY created_at ASC",
                (subject_type, subject_id, SHARE_ACTIVE),
            ).fetchall()
        return [share for share in (_row_to_share(row) for row in rows) if share]

    def find_share(
        self, *, kb_id: str, subject_type: str, subject_id: str, document_ids: tuple[str, ...]
    ) -> ShareRecord | None:
        """同一主体 + 同一文件子集视为同一条共享（用于「再次提交」时合并）。"""
        key = json.dumps(sorted(document_ids), ensure_ascii=False)
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM kb_shares WHERE kb_id = ? AND subject_type = ? AND subject_id = ? "
                "AND document_ids = ?",
                (kb_id, subject_type, subject_id, key),
            ).fetchone()
        return _row_to_share(row)

    def create_share(
        self,
        *,
        kb_id: str,
        subject_type: str,
        subject_id: str,
        can_search: bool,
        can_list: bool,
        can_read: bool,
        can_write: bool,
        requested_by: str,
        status: str,
        document_ids: tuple[str, ...] = (),
        reason: str = "",
        created_at: str,
        share_id: str | None = None,
    ) -> ShareRecord:
        resolved_id = share_id or new_share_id()
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO kb_shares (
                    share_id, kb_id, subject_type, subject_id,
                    can_search, can_list, can_read, can_write,
                    document_ids, status, requested_by, reason,
                    decided_by, decided_at, decision_note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '', ?)
                """,
                (
                    resolved_id,
                    kb_id,
                    subject_type,
                    subject_id,
                    int(can_search),
                    int(can_list),
                    int(can_read),
                    int(can_write),
                    json.dumps(sorted(document_ids), ensure_ascii=False),
                    status,
                    requested_by,
                    reason,
                    created_at,
                ),
            )
            connection.commit()
        record = self.get_share(resolved_id)
        assert record is not None
        return record

    def update_share_permissions(
        self,
        share_id: str,
        *,
        can_search: bool,
        can_list: bool,
        can_read: bool,
        can_write: bool,
        status: str | None = None,
    ) -> None:
        fields = [
            "can_search = ?",
            "can_list = ?",
            "can_read = ?",
            "can_write = ?",
        ]
        params: list[object] = [int(can_search), int(can_list), int(can_read), int(can_write)]
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        params.append(share_id)
        with self._database.connect() as connection:
            connection.execute(
                f"UPDATE kb_shares SET {', '.join(fields)} WHERE share_id = ?", params
            )
            connection.commit()

    def decide_share(
        self, share_id: str, *, status: str, decided_by: str, decided_at: str, note: str = ""
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE kb_shares SET status = ?, decided_by = ?, decided_at = ?, "
                "decision_note = ? WHERE share_id = ?",
                (status, decided_by, decided_at, note, share_id),
            )
            connection.commit()

    def delete_share(self, share_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute("DELETE FROM kb_shares WHERE share_id = ?", (share_id,))
            connection.commit()

    def delete_shares_for_subject(self, subject_type: str, subject_id: str) -> None:
        """分组被删除时清理它的共享记录（避免悬空主体）。"""
        with self._database.connect() as connection:
            connection.execute(
                "DELETE FROM kb_shares WHERE subject_type = ? AND subject_id = ?",
                (subject_type, subject_id),
            )
            connection.commit()

    def count_pending(self) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM kb_shares WHERE status = ?", (SHARE_PENDING,)
            ).fetchone()
        return int(row["n"]) if row else 0
