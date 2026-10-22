"""技能 API：Agent 可调用技能的 CRUD + 从文档生成技能草稿。

内置技能（``builtin=true``）不可删除（重启会被 seed 复活），只能编辑或停用。

``POST /api/skills/generate`` 只返回**草稿**、不落库：用户在前端审核/编辑后
再走 ``POST /api/skills`` 保存（避免低质量生成污染技能库）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_skill_generation_service, get_skill_service
from app.models.schemas import (
    ErrorResponse,
    SkillCreate,
    SkillDraft,
    SkillDuplicate,
    SkillGenerateRequest,
    SkillGenerateResponse,
    SkillInfo,
    SkillListResponse,
    SkillResourceCreate,
    SkillResourceInfo,
    SkillResourceListResponse,
    SkillResourceUpdate,
    SkillUpdate,
)
from app.services.skill_generation_service import (
    SkillDocumentEmptyError,
    SkillDocumentNotFoundError,
    SkillGenerationError,
    SkillGenerationService,
)
from app.services.skill_service import (
    BuiltinSkillProtectedError,
    SkillNotFoundError,
    SkillResourceNameConflictError,
    SkillResourceNotFoundError,
    SkillService,
)

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _info(record) -> SkillInfo:
    return SkillInfo(
        skill_id=record.skill_id,
        name=record.name,
        description=record.description,
        content=record.content,
        enabled=record.enabled,
        builtin=record.builtin,
        created_at=record.created_at,
        updated_at=record.updated_at,
        source_filename=record.source_filename,
    )


def _resource_info(record) -> SkillResourceInfo:
    return SkillResourceInfo(
        resource_id=record.resource_id,
        skill_id=record.skill_id,
        name=record.name,
        content=record.content,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _error(status: int, error_type: str, detail: str) -> JSONResponse:
    body = ErrorResponse(error=error_type, error_type=error_type, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump())


def _not_found(exc: SkillNotFoundError) -> JSONResponse:
    return _error(404, "skill_not_found", str(exc))


@router.get("", response_model=SkillListResponse)
async def list_skills(service: SkillService = Depends(get_skill_service)) -> SkillListResponse:
    return SkillListResponse(skills=[_info(record) for record in await service.list_skills()])


@router.post("", response_model=SkillInfo)
async def create_skill(
    payload: SkillCreate, service: SkillService = Depends(get_skill_service)
) -> SkillInfo:
    record = await service.create_skill(
        name=payload.name,
        description=payload.description,
        content=payload.content,
        source_filename=payload.source_filename,
    )
    return _info(record)


@router.post("/generate", response_model=SkillGenerateResponse)
async def generate_skill(
    payload: SkillGenerateRequest,
    service: SkillGenerationService = Depends(get_skill_generation_service),
) -> SkillGenerateResponse | JSONResponse:
    """根据知识库文档生成技能草稿（不落库）。"""
    try:
        result = await service.generate(document_ids=payload.document_ids, hint=payload.hint)
    except SkillDocumentNotFoundError as exc:
        return _error(404, exc.error_type, exc.message)
    except SkillDocumentEmptyError as exc:
        return _error(422, exc.error_type, exc.message)
    except SkillGenerationError as exc:
        return _error(502, exc.error_type, exc.message)

    return SkillGenerateResponse(
        draft=SkillDraft(
            name=result.name,
            description=result.description,
            content=result.content,
            source_filename=result.source_filename,
        ),
        truncated=result.truncated,
        warnings=result.warnings,
        duplicate_of=(
            SkillDuplicate(skill_id=result.duplicate_of[0], name=result.duplicate_of[1])
            if result.duplicate_of
            else None
        ),
    )


@router.get("/{skill_id}/resources", response_model=SkillResourceListResponse)
async def list_skill_resources(
    skill_id: str, service: SkillService = Depends(get_skill_service)
) -> SkillResourceListResponse | JSONResponse:
    try:
        resources = await service.list_resources(skill_id)
    except SkillNotFoundError as exc:
        return _not_found(exc)
    return SkillResourceListResponse(resources=[_resource_info(item) for item in resources])


@router.post("/{skill_id}/resources", response_model=SkillResourceInfo)
async def create_skill_resource(
    skill_id: str,
    payload: SkillResourceCreate,
    service: SkillService = Depends(get_skill_service),
) -> SkillResourceInfo | JSONResponse:
    try:
        record = await service.create_resource(skill_id, name=payload.name, content=payload.content)
    except SkillNotFoundError as exc:
        return _not_found(exc)
    except SkillResourceNameConflictError as exc:
        return _error(409, "skill_resource_name_conflict", str(exc))
    return _resource_info(record)


@router.put("/{skill_id}/resources/{resource_id}", response_model=SkillResourceInfo)
async def update_skill_resource(
    skill_id: str,
    resource_id: str,
    payload: SkillResourceUpdate,
    service: SkillService = Depends(get_skill_service),
) -> SkillResourceInfo | JSONResponse:
    try:
        record = await service.update_resource(
            skill_id,
            resource_id,
            name=payload.name,
            content=payload.content,
        )
    except SkillNotFoundError as exc:
        return _not_found(exc)
    except SkillResourceNotFoundError as exc:
        return _error(404, "skill_resource_not_found", str(exc))
    except SkillResourceNameConflictError as exc:
        return _error(409, "skill_resource_name_conflict", str(exc))
    return _resource_info(record)


@router.delete("/{skill_id}/resources/{resource_id}", response_model=None)
async def delete_skill_resource(
    skill_id: str,
    resource_id: str,
    service: SkillService = Depends(get_skill_service),
) -> dict[str, str] | JSONResponse:
    try:
        await service.delete_resource(skill_id, resource_id)
    except SkillNotFoundError as exc:
        return _not_found(exc)
    except SkillResourceNotFoundError as exc:
        return _error(404, "skill_resource_not_found", str(exc))
    return {"status": "deleted"}


@router.put("/{skill_id}", response_model=SkillInfo)
async def update_skill(
    skill_id: str,
    payload: SkillUpdate,
    service: SkillService = Depends(get_skill_service),
) -> SkillInfo | JSONResponse:
    try:
        record = await service.update_skill(
            skill_id,
            name=payload.name,
            description=payload.description,
            content=payload.content,
            enabled=payload.enabled,
        )
    except SkillNotFoundError as exc:
        return _not_found(exc)
    return _info(record)


@router.delete("/{skill_id}", response_model=None)
async def delete_skill(
    skill_id: str, service: SkillService = Depends(get_skill_service)
) -> dict[str, str] | JSONResponse:
    try:
        await service.delete_skill(skill_id)
    except SkillNotFoundError as exc:
        return _not_found(exc)
    except BuiltinSkillProtectedError as exc:
        return _error(409, "skill_builtin_protected", str(exc))
    return {"status": "deleted"}
