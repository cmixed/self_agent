"""API Key 管理（需登录）：成员管自己的，管理员可替任一成员签发。

明文密钥只在创建响应里出现一次，之后只有摘要可查——丢了就吊销重签。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import build_api_key_service, get_current_user
from app.memory.users import UserRecord
from app.models.public_schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreated,
    ApiKeyListResponse,
    ApiKeyOut,
)
from app.services.api_key_service import ApiKeyError

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


def _to_out(record) -> ApiKeyOut:
    return ApiKeyOut(
        key_id=record.key_id,
        user_id=record.user_id,
        label=record.label,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
    )


@router.get("", response_model=ApiKeyListResponse)
async def list_api_keys(
    user_id: str | None = Query(default=None, description="管理员可查看指定成员"),
    user: UserRecord = Depends(get_current_user),
) -> ApiKeyListResponse:
    service = build_api_key_service()
    keys = service.list_keys(user_id=user.user_id, is_admin=user.is_admin, target_user_id=user_id)
    return ApiKeyListResponse(items=[_to_out(item) for item in keys])


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    user: UserRecord = Depends(get_current_user),
) -> ApiKeyCreated:
    target = payload.user_id or user.user_id
    if target != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员可以替其他成员签发密钥")
    try:
        record, raw = build_api_key_service().issue(user_id=target, label=payload.label)
    except ApiKeyError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return ApiKeyCreated(**_to_out(record).model_dump(), key=raw)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: str,
    user: UserRecord = Depends(get_current_user),
) -> Response:
    try:
        build_api_key_service().revoke(key_id, user_id=user.user_id, is_admin=user.is_admin)
    except ApiKeyError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
