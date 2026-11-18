"""成员管理（仅管理员）。

单团队多成员模型：一个部署 = 一个团队，成员由管理员在此维护。
删除成员采用「停用」而不是物理删除，避免任务、记忆等外键悬空。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.auth import to_member
from app.api.deps import build_auth_service, build_user_repository, require_admin
from app.auth.service import AuthError
from app.memory.users import UserRecord
from app.models.auth_schemas import (
    AdminResetPasswordRequest,
    CreateMemberRequest,
    MemberListResponse,
    MemberOut,
    UpdateMemberRequest,
)

router = APIRouter(prefix="/api/members", tags=["members"])


def _http_error(exc: AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


@router.get("", response_model=MemberListResponse)
async def list_members(_: UserRecord = Depends(require_admin)) -> MemberListResponse:
    users = build_user_repository().list_all()
    return MemberListResponse(items=[to_member(user) for user in users])


@router.post("", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def create_member(
    payload: CreateMemberRequest,
    _: UserRecord = Depends(require_admin),
) -> MemberOut:
    try:
        user = build_auth_service().create_member(
            username=payload.username,
            display_name=payload.display_name,
            email=payload.email,
            password=payload.password,
            role=payload.role,
        )
    except AuthError as exc:
        raise _http_error(exc) from exc
    return to_member(user)


@router.patch("/{user_id}", response_model=MemberOut)
async def update_member(
    user_id: str,
    payload: UpdateMemberRequest,
    _: UserRecord = Depends(require_admin),
) -> MemberOut:
    try:
        user = build_auth_service().update_member(
            user_id,
            display_name=payload.display_name,
            email=payload.email,
            role=payload.role,
            status=payload.status,
        )
    except AuthError as exc:
        raise _http_error(exc) from exc
    return to_member(user)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_member_password(
    user_id: str,
    payload: AdminResetPasswordRequest,
    _: UserRecord = Depends(require_admin),
) -> Response:
    try:
        build_auth_service().reset_password_by_admin(user_id, payload.new_password)
    except AuthError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
