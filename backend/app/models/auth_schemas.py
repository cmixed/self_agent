"""登录与成员管理的请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    account: str = Field(description="用户名或邮箱")
    password: str


class MemberOut(BaseModel):
    user_id: str
    username: str | None = None
    display_name: str
    email: str | None = None
    role: str
    status: str
    created_at: str
    last_login_at: str | None = None


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    user: MemberOut


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ResetRequestRequest(BaseModel):
    account: str


class ResetRequestResponse(BaseModel):
    sent: bool
    email_hint: str | None = None
    message: str


class ResetConfirmRequest(BaseModel):
    account: str
    code: str
    new_password: str


class CreateMemberRequest(BaseModel):
    username: str
    display_name: str = ""
    email: str | None = None
    password: str
    role: str = "member"


class UpdateMemberRequest(BaseModel):
    display_name: str | None = None
    email: str | None = None
    role: str | None = None
    status: str | None = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str


class MemberListResponse(BaseModel):
    items: list[MemberOut]
