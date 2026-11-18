"""成员与登录态仓储（团队版，方案A：单团队多成员）。

表结构见 ``app/memory/sqlite.py``：``users`` / ``auth_tokens`` / ``password_reset_codes``。
本模块只负责 SQL 与行映射，业务判断放在 ``app/auth/service.py``。
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.memory.sqlite import SqliteDatabase

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    username: str | None
    display_name: str
    email: str | None
    role: str
    status: str
    created_at: str
    last_login_at: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE


def _row_to_user(row: sqlite3.Row | None) -> UserRecord | None:
    if row is None:
        return None
    keys = row.keys()
    return UserRecord(
        user_id=str(row["user_id"]),
        username=(row["username"] if "username" in keys else None),
        display_name=str(row["display_name"] or row["user_id"]),
        email=(row["email"] if "email" in keys else None),
        role=str(row["role"] if "role" in keys else ROLE_MEMBER),
        status=str(row["status"] if "status" in keys else STATUS_ACTIVE),
        created_at=str(row["created_at"]),
        last_login_at=(row["last_login_at"] if "last_login_at" in keys else None),
    )


def new_user_id() -> str:
    return f"u-{uuid.uuid4().hex[:12]}"


class UserRepository:
    """成员、令牌、重置验证码的持久化操作。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    # ---------- 成员 ----------

    def get_by_id(self, user_id: str) -> UserRecord | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_user(row)

    def get_by_username(self, username: str) -> UserRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE lower(username) = lower(?)", (username.strip(),)
            ).fetchone()
        return _row_to_user(row)

    def get_by_email(self, email: str) -> UserRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE lower(email) = lower(?)", (email.strip(),)
            ).fetchone()
        return _row_to_user(row)

    def list_all(self) -> list[UserRecord]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
        return [user for user in (_row_to_user(row) for row in rows) if user]

    def count_admins(self) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role = ? AND status = ?",
                (ROLE_ADMIN, STATUS_ACTIVE),
            ).fetchone()
        return int(row["n"]) if row else 0

    def create(
        self,
        *,
        username: str,
        display_name: str,
        email: str | None,
        password_hash: str,
        role: str = ROLE_MEMBER,
        user_id: str | None = None,
        created_at: str,
    ) -> UserRecord:
        resolved_id = user_id or new_user_id()
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    user_id, display_name, created_at,
                    username, email, password_hash, role, status, last_login_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    resolved_id,
                    display_name,
                    created_at,
                    username,
                    email,
                    password_hash,
                    role,
                    STATUS_ACTIVE,
                ),
            )
            connection.commit()
        record = self.get_by_id(resolved_id)
        assert record is not None
        return record

    def update_profile(
        self, user_id: str, *, display_name: str | None = None, email: str | None = None
    ) -> None:
        fields: list[str] = []
        params: list[object] = []
        if display_name is not None:
            fields.append("display_name = ?")
            params.append(display_name)
        if email is not None:
            fields.append("email = ?")
            params.append(email or None)
        if not fields:
            return
        params.append(user_id)
        with self._database.connect() as connection:
            connection.execute(f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?", params)
            connection.commit()

    def update_credentials(
        self,
        user_id: str,
        *,
        username: str | None = None,
        password_hash: str | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[object] = []
        if username is not None:
            fields.append("username = ?")
            params.append(username)
        if password_hash is not None:
            fields.append("password_hash = ?")
            params.append(password_hash)
        if not fields:
            return
        params.append(user_id)
        with self._database.connect() as connection:
            connection.execute(f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?", params)
            connection.commit()

    def set_role(self, user_id: str, role: str) -> None:
        with self._database.connect() as connection:
            connection.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
            connection.commit()

    def set_status(self, user_id: str, status: str) -> None:
        with self._database.connect() as connection:
            connection.execute("UPDATE users SET status = ? WHERE user_id = ?", (status, user_id))
            connection.commit()

    def touch_login(self, user_id: str, now: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE users SET last_login_at = ? WHERE user_id = ?", (now, user_id)
            )
            connection.commit()

    def get_password_hash(self, user_id: str) -> str | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return (row["password_hash"] if row else None) or None

    # ---------- 登录令牌 ----------

    def create_token(self, *, user_id: str, digest: str, created_at: str, expires_at: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "INSERT INTO auth_tokens (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (digest, user_id, created_at, expires_at),
            )
            connection.commit()

    def find_token(self, digest: str) -> tuple[str, str] | None:
        """返回 ``(user_id, expires_at)``；令牌不存在时返回 None。"""
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT user_id, expires_at FROM auth_tokens WHERE token_hash = ?", (digest,)
            ).fetchone()
        if row is None:
            return None
        return str(row["user_id"]), str(row["expires_at"])

    def delete_token(self, digest: str) -> None:
        with self._database.connect() as connection:
            connection.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (digest,))
            connection.commit()

    def delete_tokens_for_user(self, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
            connection.commit()

    def purge_expired_tokens(self, now: str) -> int:
        with self._database.connect() as connection:
            cursor = connection.execute("DELETE FROM auth_tokens WHERE expires_at <= ?", (now,))
            connection.commit()
            return int(cursor.rowcount or 0)

    # ---------- 重置验证码 ----------

    def create_reset_code(
        self, *, user_id: str, digest: str, created_at: str, expires_at: str
    ) -> None:
        with self._database.connect() as connection:
            # 同一账号只保留最新一条：旧码在发新码时立即失效
            connection.execute("DELETE FROM password_reset_codes WHERE user_id = ?", (user_id,))
            connection.execute(
                "INSERT INTO password_reset_codes "
                "(user_id, code_hash, created_at, expires_at, used_at, attempts) "
                "VALUES (?, ?, ?, ?, NULL, 0)",
                (user_id, digest, created_at, expires_at),
            )
            connection.commit()

    def get_reset_code(self, user_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM password_reset_codes WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "code_hash": row["code_hash"],
            "expires_at": row["expires_at"],
            "used_at": row["used_at"],
            "attempts": int(row["attempts"]),
        }

    def bump_reset_attempts(self, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE password_reset_codes SET attempts = attempts + 1 WHERE user_id = ?",
                (user_id,),
            )
            connection.commit()

    def consume_reset_code(self, user_id: str, now: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE password_reset_codes SET used_at = ? WHERE user_id = ?", (now, user_id)
            )
            connection.commit()
