"""登录、登出、改密与邮箱验证码重置。

设计要点（对应「团队版」改造）：
- 账号 = 用户名（或邮箱）+ 口令；口令只存 PBKDF2 散列。
- 登录令牌不落明文：库里只存 sha256 摘要，退出即删除。
- 重置密码走邮箱验证码：一次性、10 分钟有效、错误 5 次作废。
- 首次启动自动创建管理员，并**沿用旧默认用户 id**，使历史任务与记忆不丢失。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.auth.passwords import PasswordError, hash_password, needs_rehash, verify_password
from app.auth.tokens import new_reset_code, new_token, reset_code_digest, token_digest
from app.core.config import Settings, get_settings
from app.memory.repository import utc_now
from app.memory.users import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    STATUS_ACTIVE,
    STATUS_DISABLED,
    UserRecord,
    UserRepository,
)


class AuthError(Exception):
    """登录/重置流程中的可预期错误；``code`` 用于前端提示与测试断言。"""

    def __init__(self, message: str, *, code: str = "auth_failed", status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass(frozen=True)
class LoginResult:
    token: str
    expires_at: str
    user: UserRecord


class AuthService:
    def __init__(
        self,
        repository: UserRepository,
        settings: Settings | None = None,
        *,
        email_service: object | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings or get_settings()
        self._email_service = email_service

    # ---------- 初始化 ----------

    def bootstrap(self) -> UserRecord:
        """确保至少有一个管理员。

        旧库里的默认用户（``settings.default_user_id``，通常为 ``local-user``）
        会被**就地升级**为管理员，这样历史任务、记忆、预设都不与新账号割裂。
        """
        admins = [user for user in self._repository.list_all() if user.is_admin and user.is_active]
        if admins:
            return admins[0]

        username = self._settings.auth_admin_username.strip() or "admin"
        password = self._settings.auth_admin_password.get_secret_value()
        email = self._settings.auth_admin_email.strip() or None
        password_hash = hash_password(password)
        now = utc_now()

        legacy = self._repository.get_by_id(self._settings.default_user_id)
        if legacy is not None:
            self._repository.update_credentials(
                legacy.user_id, username=username, password_hash=password_hash
            )
            self._repository.set_role(legacy.user_id, ROLE_ADMIN)
            self._repository.set_status(legacy.user_id, STATUS_ACTIVE)
            self._repository.update_profile(
                legacy.user_id,
                display_name=legacy.display_name or username,
                email=email,
            )
            upgraded = self._repository.get_by_id(legacy.user_id)
            assert upgraded is not None
            return upgraded

        return self._repository.create(
            username=username,
            display_name=username,
            email=email,
            password_hash=password_hash,
            role=ROLE_ADMIN,
            user_id=self._settings.default_user_id,
            created_at=now,
        )

    # ---------- 登录 / 登出 ----------

    def login(self, account: str, password: str) -> LoginResult:
        account = (account or "").strip()
        if not account or not password:
            raise AuthError("请输入账号与密码", code="invalid_input", status=400)

        user = self._repository.get_by_username(account) or self._repository.get_by_email(account)
        stored = self._repository.get_password_hash(user.user_id) if user else None
        if user is None or not verify_password(password, stored):
            # 账号不存在与密码错误返回同一提示，避免枚举
            raise AuthError("账号或密码不正确", code="invalid_credentials", status=401)
        if not user.is_active:
            raise AuthError("该账号已被停用，请联系管理员", code="account_disabled", status=403)

        if needs_rehash(stored):
            self._repository.update_credentials(user.user_id, password_hash=hash_password(password))

        token = new_token()
        now = datetime.now(UTC)
        expires_at = (now + timedelta(hours=self._settings.auth_token_ttl_hours)).isoformat()
        self._repository.purge_expired_tokens(now.isoformat())
        self._repository.create_token(
            user_id=user.user_id,
            digest=token_digest(token),
            created_at=now.isoformat(),
            expires_at=expires_at,
        )
        self._repository.touch_login(user.user_id, now.isoformat())
        refreshed = self._repository.get_by_id(user.user_id) or user
        return LoginResult(token=token, expires_at=expires_at, user=refreshed)

    def resolve_token(self, token: str) -> UserRecord | None:
        """令牌 → 成员；过期、停用、删除一律返回 None。"""
        if not token:
            return None
        found = self._repository.find_token(token_digest(token))
        if found is None:
            return None
        user_id, expires_at = found
        try:
            if datetime.fromisoformat(expires_at) <= datetime.now(UTC):
                self._repository.delete_token(token_digest(token))
                return None
        except ValueError:
            self._repository.delete_token(token_digest(token))
            return None
        user = self._repository.get_by_id(user_id)
        if user is None or not user.is_active:
            return None
        return user

    def logout(self, token: str) -> None:
        if token:
            self._repository.delete_token(token_digest(token))

    # ---------- 改密 ----------

    def change_password(self, user_id: str, old_password: str, new_password: str) -> None:
        stored = self._repository.get_password_hash(user_id)
        if not verify_password(old_password, stored):
            raise AuthError("原密码不正确", code="invalid_credentials", status=400)
        try:
            self._repository.update_credentials(user_id, password_hash=hash_password(new_password))
        except PasswordError as exc:
            raise AuthError(str(exc), code="weak_password", status=400) from exc
        # 改密后踢掉其它设备的登录态
        self._repository.delete_tokens_for_user(user_id)

    def reset_password_by_admin(self, user_id: str, new_password: str) -> None:
        try:
            self._repository.update_credentials(user_id, password_hash=hash_password(new_password))
        except PasswordError as exc:
            raise AuthError(str(exc), code="weak_password", status=400) from exc
        self._repository.delete_tokens_for_user(user_id)

    # ---------- 邮箱验证码重置 ----------

    async def request_reset(self, account: str) -> str | None:
        """生成验证码并发送；返回掩码后的邮箱用于前端提示。

        账号不存在时**不报错**（避免枚举），返回 None。
        """
        user = self._repository.get_by_username(account) or self._repository.get_by_email(account)
        if user is None or not user.is_active or not user.email:
            return None

        code = new_reset_code()
        now = datetime.now(UTC)
        expires_at = (now + timedelta(minutes=self._settings.reset_code_ttl_minutes)).isoformat()
        self._repository.create_reset_code(
            user_id=user.user_id,
            digest=reset_code_digest(user.user_id, code),
            created_at=now.isoformat(),
            expires_at=expires_at,
        )

        if self._email_service is None:
            raise AuthError(
                "邮件服务未配置，无法发送验证码；请联系管理员在设置中填写 SMTP",
                code="email_not_configured",
                status=503,
            )
        await self._email_service.send_reset_code(  # type: ignore[attr-defined]
            to=user.email,
            code=code,
            minutes=self._settings.reset_code_ttl_minutes,
        )
        return _mask_email(user.email)

    def confirm_reset(self, account: str, code: str, new_password: str) -> None:
        user = self._repository.get_by_username(account) or self._repository.get_by_email(account)
        if user is None:
            raise AuthError("验证码无效或已过期", code="invalid_code", status=400)

        record = self._repository.get_reset_code(user.user_id)
        if record is None or record["used_at"]:
            raise AuthError("验证码无效或已过期，请重新获取", code="invalid_code", status=400)

        if int(record["attempts"]) >= self._settings.reset_code_max_attempts:
            raise AuthError("错误次数过多，请重新获取验证码", code="too_many_attempts", status=429)

        try:
            expired = datetime.fromisoformat(str(record["expires_at"])) <= datetime.now(UTC)
        except ValueError:
            expired = True
        if expired:
            raise AuthError("验证码已过期，请重新获取", code="code_expired", status=400)

        if reset_code_digest(user.user_id, (code or "").strip()) != record["code_hash"]:
            self._repository.bump_reset_attempts(user.user_id)
            raise AuthError("验证码不正确", code="invalid_code", status=400)

        try:
            self._repository.update_credentials(
                user.user_id, password_hash=hash_password(new_password)
            )
        except PasswordError as exc:
            raise AuthError(str(exc), code="weak_password", status=400) from exc

        self._repository.consume_reset_code(user.user_id, utc_now())
        self._repository.delete_tokens_for_user(user.user_id)

    # ---------- 成员管理 ----------

    def create_member(
        self,
        *,
        username: str,
        display_name: str,
        email: str | None,
        password: str,
        role: str = ROLE_MEMBER,
    ) -> UserRecord:
        username = (username or "").strip()
        if not username:
            raise AuthError("用户名不能为空", code="invalid_input", status=400)
        if self._repository.get_by_username(username) is not None:
            raise AuthError("用户名已存在", code="username_taken", status=409)
        if email and self._repository.get_by_email(email) is not None:
            raise AuthError("邮箱已被占用", code="email_taken", status=409)
        try:
            password_hash = hash_password(password)
        except PasswordError as exc:
            raise AuthError(str(exc), code="weak_password", status=400) from exc
        return self._repository.create(
            username=username,
            display_name=(display_name or username).strip(),
            email=(email or "").strip() or None,
            password_hash=password_hash,
            role=role if role in (ROLE_ADMIN, ROLE_MEMBER) else ROLE_MEMBER,
            created_at=utc_now(),
        )

    def update_member(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        email: str | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> UserRecord:
        user = self._repository.get_by_id(user_id)
        if user is None:
            raise AuthError("成员不存在", code="not_found", status=404)

        if role == ROLE_MEMBER and user.is_admin:
            if self._repository.count_admins() <= 1:
                raise AuthError("至少保留一名管理员", code="last_admin", status=400)
        if status == STATUS_DISABLED and user.is_admin:
            if self._repository.count_admins() <= 1:
                raise AuthError("至少保留一名管理员", code="last_admin", status=400)

        self._repository.update_profile(user_id, display_name=display_name, email=email)
        if role in (ROLE_ADMIN, ROLE_MEMBER) and role != user.role:
            self._repository.set_role(user_id, role)
        if status in (STATUS_ACTIVE, STATUS_DISABLED) and status != user.status:
            self._repository.set_status(user_id, status)
            if status == STATUS_DISABLED:
                self._repository.delete_tokens_for_user(user_id)

        refreshed = self._repository.get_by_id(user_id)
        assert refreshed is not None
        return refreshed


def _mask_email(value: str) -> str:
    name, _, domain = value.partition("@")
    if not domain:
        return value[:2] + "***"
    visible = name[:2] if len(name) > 2 else name[:1]
    return f"{visible}***@{domain}"
