"""API Key 仓储：对外接口鉴权用。

密钥只存 sha256 摘要；``last_used_at`` 每次调用更新（用于排查「这个 key 还在用吗」）。
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from app.memory.sqlite import SqliteDatabase


@dataclass(frozen=True)
class ApiKeyRecord:
    key_id: str
    user_id: str
    label: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None

    @property
    def active(self) -> bool:
        return not self.revoked_at


def _row_to_key(row: sqlite3.Row | None) -> ApiKeyRecord | None:
    if row is None:
        return None
    return ApiKeyRecord(
        key_id=str(row["key_id"]),
        user_id=str(row["user_id"]),
        label=str(row["label"] or ""),
        created_at=str(row["created_at"]),
        last_used_at=row["last_used_at"],
        revoked_at=row["revoked_at"],
    )


def new_key_id() -> str:
    return f"k-{uuid.uuid4().hex[:12]}"


class ApiKeyRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, *, key_id: str, user_id: str, label: str, key_hash: str, created_at: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "INSERT INTO api_keys (key_id, user_id, label, key_hash, created_at, "
                "last_used_at, revoked_at) VALUES (?, ?, ?, ?, ?, NULL, NULL)",
                (key_id, user_id, label, key_hash, created_at),
            )
            connection.commit()

    def list_for_user(self, user_id: str) -> list[ApiKeyRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        return [key for key in (_row_to_key(row) for row in rows) if key]

    def list_all(self) -> list[ApiKeyRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM api_keys ORDER BY created_at DESC"
            ).fetchall()
        return [key for key in (_row_to_key(row) for row in rows) if key]

    def find_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
            ).fetchone()
        return _row_to_key(row)

    def get(self, key_id: str) -> ApiKeyRecord | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM api_keys WHERE key_id = ?", (key_id,)).fetchone()
        return _row_to_key(row)

    def revoke(self, key_id: str, revoked_at: str) -> bool:
        with self._database.connect() as connection:
            cursor = connection.execute(
                "UPDATE api_keys SET revoked_at = ? WHERE key_id = ? AND revoked_at IS NULL",
                (revoked_at, key_id),
            )
            connection.commit()
            return bool(cursor.rowcount)

    def touch(self, key_id: str, used_at: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE key_id = ?", (used_at, key_id)
            )
            connection.commit()
