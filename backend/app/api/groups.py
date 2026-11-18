"""团队分组接口（「一批人」的载体）。

建组 / 拉人 / 申请加入 / 组内审批：组内编辑者可以同意入组（默认路径），
管理员可直接拉人或审批；组本身不携带任何内容权限，只作为共享的授予对象。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user, get_group_service
from app.memory.users import UserRecord
from app.models.kb_schemas import (
    AddGroupMemberRequest,
    CreateGroupRequest,
    GroupListResponse,
    GroupMemberOut,
    GroupOut,
    UpdateGroupRequest,
)
from app.services.group_service import GroupError, GroupService

router = APIRouter(prefix="/api/groups", tags=["groups"])


def _http_error(exc: GroupError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _group_out(payload: dict[str, object]) -> GroupOut:
    data = dict(payload)
    data["members"] = [GroupMemberOut(**item) for item in data.get("members", [])]  # type: ignore[arg-type,union-attr]
    return GroupOut(**data)  # type: ignore[arg-type]


@router.get("", response_model=GroupListResponse)
async def list_groups(
    service: GroupService = Depends(get_group_service),
    user: UserRecord = Depends(get_current_user),
) -> GroupListResponse:
    rows = service.list_groups(user)
    return GroupListResponse(items=[_group_out(row) for row in rows])


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: CreateGroupRequest,
    service: GroupService = Depends(get_group_service),
    user: UserRecord = Depends(get_current_user),
) -> GroupOut:
    try:
        group = service.create(name=payload.name, description=payload.description, user=user)
    except GroupError as exc:
        raise _http_error(exc) from exc
    rows = service.list_groups(user)
    row = next((item for item in rows if item["group_id"] == group.group_id), None)
    assert row is not None
    return _group_out(row)


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: str,
    payload: UpdateGroupRequest,
    service: GroupService = Depends(get_group_service),
    user: UserRecord = Depends(get_current_user),
) -> GroupOut:
    try:
        service.update(group_id, name=payload.name, description=payload.description, user=user)
    except GroupError as exc:
        raise _http_error(exc) from exc
    rows = service.list_groups(user)
    row = next((item for item in rows if item["group_id"] == group_id), None)
    assert row is not None
    return _group_out(row)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: str,
    service: GroupService = Depends(get_group_service),
    user: UserRecord = Depends(get_current_user),
) -> None:
    try:
        service.delete(group_id, user=user)
    except GroupError as exc:
        raise _http_error(exc) from exc


@router.post("/{group_id}/members", response_model=GroupOut)
async def add_member(
    group_id: str,
    payload: AddGroupMemberRequest,
    service: GroupService = Depends(get_group_service),
    user: UserRecord = Depends(get_current_user),
) -> GroupOut:
    """管理员/组内编辑者直接拉人；普通成员只能拉自己（即申请加入）。"""
    try:
        if payload.user_id != user.user_id:
            service.add_member(group_id, user_id=payload.user_id, role=payload.role, actor=user)
        else:
            service.request_join(group_id, actor=user)
    except GroupError as exc:
        raise _http_error(exc) from exc
    rows = service.list_groups(user)
    row = next((item for item in rows if item["group_id"] == group_id), None)
    assert row is not None
    return _group_out(row)


@router.post("/{group_id}/join", response_model=GroupOut)
async def join_group(
    group_id: str,
    service: GroupService = Depends(get_group_service),
    user: UserRecord = Depends(get_current_user),
) -> GroupOut:
    """申请加入：进入待审批状态，由组内编辑者或管理员同意。"""
    try:
        service.request_join(group_id, actor=user)
    except GroupError as exc:
        raise _http_error(exc) from exc
    rows = service.list_groups(user)
    row = next((item for item in rows if item["group_id"] == group_id), None)
    assert row is not None
    return _group_out(row)


@router.post("/{group_id}/members/{user_id}/decide", response_model=GroupOut)
async def decide_member(
    group_id: str,
    user_id: str,
    approve: bool = True,
    service: GroupService = Depends(get_group_service),
    user: UserRecord = Depends(get_current_user),
) -> GroupOut:
    try:
        service.decide_member(group_id, user_id=user_id, approve=approve, actor=user)
    except GroupError as exc:
        raise _http_error(exc) from exc
    rows = service.list_groups(user)
    row = next((item for item in rows if item["group_id"] == group_id), None)
    assert row is not None
    return _group_out(row)


@router.patch("/{group_id}/members/{user_id}", response_model=GroupOut)
async def set_member_role(
    group_id: str,
    user_id: str,
    role: str,
    service: GroupService = Depends(get_group_service),
    user: UserRecord = Depends(get_current_user),
) -> GroupOut:
    try:
        service.set_role(group_id, user_id=user_id, role=role, actor=user)
    except GroupError as exc:
        raise _http_error(exc) from exc
    rows = service.list_groups(user)
    row = next((item for item in rows if item["group_id"] == group_id), None)
    assert row is not None
    return _group_out(row)


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: str,
    user_id: str,
    service: GroupService = Depends(get_group_service),
    user: UserRecord = Depends(get_current_user),
) -> None:
    try:
        service.remove_member(group_id, user_id=user_id, actor=user)
    except GroupError as exc:
        raise _http_error(exc) from exc
