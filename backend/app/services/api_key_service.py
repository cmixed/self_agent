"""API Key 服务：签发、吊销、校验。

对外接口（``/api/v1/*``）用 ``X-API-Key`` 鉴权，权限与该 key 所属成员完全一致：
可见范围、检索范围都按成员身份收敛，不因为「是接口调用」而放宽。
"""

from __future__ import annotations

import secrets

from app.auth.tokens import token_digest
from app.memory.api_keys import ApiKeyRecord, ApiKeyRepository, new_key_id
from app.memory.repository import utc_now
from app.memory.users import UserRecord, UserRepository

KEY_PREFIX = "kb"


class ApiKeyError(Exception):
    def __init__(self, message: str, *, status: int = 400, code: str = "api_key_error") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class ApiKeyService:
    def __init__(self, repository: ApiKeyRepository, users: UserRepository) -> None:
        self._repository = repository
        self._users = users

    def issue(self, *, user_id: str, label: str) -> tuple[ApiKeyRecord, str]:
        user = self._users.get_by_id(user_id)
        if user is None:
            raise ApiKeyError("成员不存在", status=404, code="user_not_found")
        if not user.is_active:
            raise ApiKeyError("该成员已停用，不能签发密钥", status=400, code="user_disabled")

        raw = f"{KEY_PREFIX}-{secrets.token_urlsafe(32)}"
        key_id = new_key_id()
        self._repository.create(
            key_id=key_id,
            user_id=user_id,
            label=(label or "").strip()[:60],
            key_hash=token_digest(raw),
            created_at=utc_now(),
        )
        record = self._repository.get(key_id)
        assert record is not None
        return record, raw

    def list_keys(self, *, user_id: str, is_admin: bool, target_user_id: str | None = None) -> list[ApiKeyRecord]:
        if is_admin and target_user_id:
            return [key for key in self._repository.list_all() if key.user_id == target_user_id]
        return self._repository.list_for_user(user_id)

    def revoke(self, key_id: str, *, user_id: str, is_admin: bool) -> None:
        record = self._repository.get(key_id)
        if record is None:
            raise ApiKeyError("密钥不存在", status=404, code="not_found")
        if not is_admin and record.user_id != user_id:
            raise ApiKeyError("无权吊销该密钥", status=403, code="forbidden")
        if not self._repository.revoke(key_id, utc_now()):
            raise ApiKeyError("密钥已被吊销", status=409, code="already_revoked")

    def authenticate(self, raw_key: str) -> UserRecord | None:
        """密钥 → 成员；无效、吊销、成员停用一律 None。"""
        raw_key = (raw_key or "").strip()
        if not raw_key:
            return None
        record = self._repository.find_by_hash(token_digest(raw_key))
        if record is None or not record.active:
            return None
        user = self._users.get_by_id(record.user_id)
        if user is None or not user.is_active:
            return None
        self._repository.touch(record.key_id, utc_now())
        return user
