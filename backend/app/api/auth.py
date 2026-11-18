"""登录、登出、改密与邮箱验证码重置接口。

约定：
- 除 ``/api/auth/login``、``/api/auth/reset/*`` 外，其余接口都需要登录态。
- 错误一律用 HTTP 状态码 + ``detail`` 文案，前端 ``ApiError`` 直接展示。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from app.api.deps import build_auth_service, get_current_user
from app.auth.service import AuthError
from app.memory.users import UserRecord
from app.models.auth_schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MemberOut,
    ResetConfirmRequest,
    ResetRequestRequest,
    ResetRequestResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def to_member(user: UserRecord) -> MemberOut:
    return MemberOut(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def _http_error(exc: AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    service = build_auth_service()
    try:
        result = service.login(payload.account, payload.password)
    except AuthError as exc:
        raise _http_error(exc) from exc
    return LoginResponse(
        token=result.token, expires_at=result.expires_at, user=to_member(result.user)
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    authorization: str | None = Header(default=None),
) -> Response:
    scheme, _, token = (authorization or "").partition(" ")
    if token and scheme.lower() == "bearer":
        build_auth_service().logout(token.strip())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MemberOut)
async def me(user: UserRecord = Depends(get_current_user)) -> MemberOut:
    return to_member(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    user: UserRecord = Depends(get_current_user),
) -> Response:
    try:
        build_auth_service().change_password(
            user.user_id, payload.old_password, payload.new_password
        )
    except AuthError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reset/request", response_model=ResetRequestResponse)
async def request_reset(payload: ResetRequestRequest) -> ResetRequestResponse:
    """发送验证码。账号不存在时同样返回成功提示，避免枚举账号。"""
    service = build_auth_service()
    try:
        hint = await service.request_reset(payload.account)
    except AuthError as exc:
        raise _http_error(exc) from exc
    if hint is None:
        return ResetRequestResponse(
            sent=False,
            email_hint=None,
            message="如果该账号已绑定邮箱，验证码已发送",
        )
    return ResetRequestResponse(sent=True, email_hint=hint, message=f"验证码已发送至 {hint}")


@router.post("/reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_reset(payload: ResetConfirmRequest) -> Response:
    try:
        build_auth_service().confirm_reset(payload.account, payload.code, payload.new_password)
    except AuthError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
