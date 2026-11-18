"""知识库与共享接口。

权限语义见 ``app/services/access.py``：同一条请求里，成员的能力是
「库主身份 + 命中的共享」的并集；管理员能看到**关系**（谁把哪个库共享给了谁），
但看不到库内容——内容仍然只看能力。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    build_knowledge_repository,
    get_category_service,
    get_current_user,
    get_document_service,
    get_knowledge_service,
    require_admin,
)
from app.memory.knowledge import SHARE_ACTIVE, SHARE_PENDING
from app.memory.users import UserRecord
from app.models.kb_schemas import (
    CreateKbRequest,
    CreateShareRequest,
    DecideShareRequest,
    GraphResponse,
    KbDetail,
    KbListResponse,
    KbSummary,
    ShareListResponse,
    ShareOut,
    UpdateKbRequest,
    UpdateShareRequest,
)
from app.models.schemas import DocumentCaps, DocumentListResponse
from app.services.access import Caps
from app.services.category_service import CategoryService
from app.services.document_service import DocumentService
from app.services.knowledge_service import KbView, KnowledgeError, KnowledgeService

router = APIRouter(prefix="/api/kb", tags=["knowledge"])
share_router = APIRouter(prefix="/api/shares", tags=["shares"])


def _http_error(exc: KnowledgeError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _caps_model(caps: Caps) -> DocumentCaps:
    return DocumentCaps(**caps.as_dict())


def _kb_summary(view: KbView) -> KbSummary:
    return KbSummary(
        kb_id=view.kb.kb_id,
        name=view.kb.name,
        description=view.kb.description,
        kind=view.kb.kind,
        owner_id=view.kb.owner_id,
        owner_name=view.owner_name,
        document_count=view.document_count,
        share_count=view.share_count,
        pending_count=view.pending_count,
        my_caps=_caps_model(view.my_caps),
        my_caps_label=view.my_caps.describe(),
        can_manage=view.can_manage,
    )


def _share_out(payload: dict[str, object]) -> ShareOut:
    data = dict(payload)
    caps = data.get("caps") or {}
    data["caps"] = DocumentCaps(**caps)  # type: ignore[arg-type]
    return ShareOut(**data)  # type: ignore[arg-type]


@router.get("", response_model=KbListResponse)
async def list_knowledge_bases(
    service: KnowledgeService = Depends(get_knowledge_service),
    user: UserRecord = Depends(get_current_user),
) -> KbListResponse:
    views = await service.list_kbs(user)
    return KbListResponse(items=[_kb_summary(view) for view in views])


@router.get("/graph", response_model=GraphResponse)
async def share_graph(
    service: KnowledgeService = Depends(get_knowledge_service),
    user: UserRecord = Depends(get_current_user),
) -> GraphResponse:
    """人 / 组 / 知识库的共享关系图（管理员看全量，成员看与自己相关的部分）。"""
    payload = await service.graph(user)
    return GraphResponse.model_validate(payload)


@router.post("", response_model=KbDetail, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: CreateKbRequest,
    service: KnowledgeService = Depends(get_knowledge_service),
    user: UserRecord = Depends(get_current_user),
) -> KbDetail:
    try:
        kb = await service.create_kb(
            name=payload.name,
            description=payload.description,
            user=user,
            kind=payload.kind,
        )
    except KnowledgeError as exc:
        raise _http_error(exc) from exc
    return await get_kb_detail(kb.kb_id, service, user)


@router.get("/{kb_id}", response_model=KbDetail)
async def get_kb_detail(
    kb_id: str,
    service: KnowledgeService = Depends(get_knowledge_service),
    user: UserRecord = Depends(get_current_user),
) -> KbDetail:
    try:
        payload = await service.kb_detail(kb_id, user)
    except KnowledgeError as exc:
        raise _http_error(exc) from exc
    data = dict(payload)
    data["my_caps"] = DocumentCaps(**data["my_caps"])  # type: ignore[arg-type]
    data["shares"] = [_share_out(item) for item in data.get("shares", [])]  # type: ignore[union-attr]
    return KbDetail(**data)  # type: ignore[arg-type]


@router.patch("/{kb_id}", response_model=KbDetail)
async def update_knowledge_base(
    kb_id: str,
    payload: UpdateKbRequest,
    service: KnowledgeService = Depends(get_knowledge_service),
    user: UserRecord = Depends(get_current_user),
) -> KbDetail:
    try:
        await service.update_kb(
            kb_id, name=payload.name, description=payload.description, user=user
        )
    except KnowledgeError as exc:
        raise _http_error(exc) from exc
    return await get_kb_detail(kb_id, service, user)


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: str,
    service: KnowledgeService = Depends(get_knowledge_service),
    user: UserRecord = Depends(get_current_user),
) -> dict[str, object]:
    """删除知识库与其文档（团队知识库受保护，不可删除）。"""
    try:
        removed = await service.delete_kb(kb_id, user=user)
    except KnowledgeError as exc:
        raise _http_error(exc) from exc
    return {"kb_id": kb_id, "status": "deleted", "documents_removed": removed}


@router.get("/{kb_id}/documents", response_model=DocumentListResponse)
async def list_kb_documents(
    kb_id: str,
    service: KnowledgeService = Depends(get_knowledge_service),
    documents: DocumentService = Depends(get_document_service),
    categories: CategoryService = Depends(get_category_service),
    user: UserRecord = Depends(get_current_user),
) -> DocumentListResponse:
    """某个知识库里的文档（按 ``list`` 能力过滤）。"""
    try:
        service.get_kb(kb_id)
    except KnowledgeError as exc:
        raise _http_error(exc) from exc
    items = await documents.list_documents(
        user_id=user.user_id, is_admin=user.is_admin, kb_id=kb_id
    )
    mapping = await categories.document_category_map()
    for item in items:
        item.category_ids = mapping.get(item.document_id, [])
    return DocumentListResponse(documents=items)


@router.post("/{kb_id}/shares", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
async def create_share(
    kb_id: str,
    payload: CreateShareRequest,
    service: KnowledgeService = Depends(get_knowledge_service),
    user: UserRecord = Depends(get_current_user),
) -> ShareOut:
    """创建共享：库主 / 管理员直接生效；其他管理者提交后等管理员审批。"""
    caps = Caps.of(
        search=payload.caps.search,
        list=payload.caps.list,
        read=payload.caps.read,
        write=payload.caps.write,
    )
    try:
        share = await service.create_share(
            kb_id,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            caps=caps,
            document_ids=payload.document_ids,
            reason=payload.reason,
            user=user,
        )
    except KnowledgeError as exc:
        raise _http_error(exc) from exc
    kb = service.get_kb(kb_id)
    return ShareOut(
        share_id=share.share_id,
        kb_id=share.kb_id,
        kb_name=kb.name,
        subject_type=share.subject_type,  # type: ignore[arg-type]
        subject_id=share.subject_id,
        caps=_caps_model(Caps.from_share(share)),
        caps_label=Caps.from_share(share).describe(),
        document_ids=list(share.document_ids),
        status=share.status,  # type: ignore[arg-type]
        reason=share.reason,
        requested_by=share.requested_by,
        created_at=share.created_at,
    )


@share_router.get("", response_model=ShareListResponse)
async def list_shares(
    view: str = Query(default="mine", pattern="^(mine|pending|all)$"),
    service: KnowledgeService = Depends(get_knowledge_service),
    user: UserRecord = Depends(get_current_user),
) -> ShareListResponse:
    """共享清单：``mine`` 与我相关、``pending`` 待我审批、``all`` 全部（管理员）。"""
    if view == "pending":
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="需要管理员权限")
        rows = [
            item for item in await service.all_shares(user) if item.get("status") == SHARE_PENDING
        ]
    elif view == "all":
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="需要管理员权限")
        rows = await service.all_shares(user)
    else:
        rows = await service.shares_for_user(user)
    items = [_share_out(item) for item in rows]
    return ShareListResponse(
        items=items,
        pending_count=len([item for item in items if item.status == SHARE_PENDING]),
    )


@share_router.post("/{share_id}/decide", response_model=ShareOut)
async def decide_share(
    share_id: str,
    payload: DecideShareRequest,
    service: KnowledgeService = Depends(get_knowledge_service),
    admin: UserRecord = Depends(require_admin),
) -> ShareOut:
    try:
        share = await service.decide_share(
            share_id, approve=payload.approve, note=payload.note, user=admin
        )
    except KnowledgeError as exc:
        raise _http_error(exc) from exc
    kb = service.get_kb(share.kb_id)
    caps = Caps.from_share(share)
    return ShareOut(
        share_id=share.share_id,
        kb_id=share.kb_id,
        kb_name=kb.name,
        subject_type=share.subject_type,  # type: ignore[arg-type]
        subject_id=share.subject_id,
        caps=_caps_model(caps),
        caps_label=caps.describe(),
        document_ids=list(share.document_ids),
        status=share.status,  # type: ignore[arg-type]
        reason=share.reason,
        requested_by=share.requested_by,
        decided_by=share.decided_by,
        decided_at=share.decided_at,
        decision_note=share.decision_note,
        created_at=share.created_at,
    )


@share_router.patch("/{share_id}", response_model=ShareOut)
async def update_share(
    share_id: str,
    payload: UpdateShareRequest,
    service: KnowledgeService = Depends(get_knowledge_service),
    user: UserRecord = Depends(get_current_user),
) -> ShareOut:
    """调整已生效共享的能力（库主 / 管理员）。"""
    repository = build_knowledge_repository()
    share = repository.get_share(share_id)
    if share is None:
        raise HTTPException(status_code=404, detail="共享记录不存在")
    if share.status != SHARE_ACTIVE:
        raise HTTPException(status_code=409, detail="只有生效中的共享可以调整权限")
    if not service.access_for(user).manage_kb(share.kb_id):
        raise HTTPException(status_code=403, detail="只有知识库管理员可以调整共享")
    caps = Caps.of(
        search=payload.caps.search,
        list=payload.caps.list,
        read=payload.caps.read,
        write=payload.caps.write,
    )
    repository.update_share_permissions(
        share_id,
        can_search=caps.search,
        can_list=caps.list,
        can_read=caps.read,
        can_write=caps.write,
    )
    kb = service.get_kb(share.kb_id)
    return ShareOut(
        share_id=share.share_id,
        kb_id=share.kb_id,
        kb_name=kb.name,
        subject_type=share.subject_type,  # type: ignore[arg-type]
        subject_id=share.subject_id,
        caps=_caps_model(caps),
        caps_label=caps.describe(),
        document_ids=list(share.document_ids),
        status=share.status,
        reason=share.reason,
        requested_by=share.requested_by,
        created_at=share.created_at,
    )


@share_router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    share_id: str,
    service: KnowledgeService = Depends(get_knowledge_service),
    user: UserRecord = Depends(get_current_user),
) -> None:
    try:
        await service.revoke_share(share_id, user=user)
    except KnowledgeError as exc:
        raise _http_error(exc) from exc
