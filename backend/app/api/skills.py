"""技能 API：Agent 可调用技能的 CRUD + 从文档生成技能草稿 + 技能包导入导出。

内置技能（``builtin=true``）不可删除（重启会被 seed 复活），只能编辑或停用。

``POST /api/skills/generate`` 只返回**草稿**、不落库：用户在前端审核/编辑后
再走 ``POST /api/skills`` 保存（避免低质量生成污染技能库）。

技能包（``SKILL.md`` + ``references/`` / ``resources/`` / ``scripts/``）：

- ``POST /api/skills/import/preview`` 上传 zip → 解析并暂存预览（不落盘）；
- ``POST /api/skills/import`` 用预览 token 确认落盘；
- ``GET  /api/skills/{id}/export`` 导出标准 zip。

脚本附件只保存，永不执行。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response

from app.api.deps import (
    get_skill_generation_service,
    get_skill_package_service,
    get_skill_service,
)
from app.models.schemas import (
    ErrorResponse,
    SkillCreate,
    SkillDraft,
    SkillDuplicate,
    SkillGenerateRequest,
    SkillGenerateResponse,
    SkillImportConfirm,
    SkillImportPreview,
    SkillInfo,
    SkillListResponse,
    SkillPackageResource,
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
from app.skills.errors import (
    SkillImportExpiredError,
    SkillPackageError,
    SkillPackageTooLargeError,
    SkillParseError,
)
from app.skills.models import SkillRecord, SkillResourceRecord
from app.skills.package import MAX_PACKAGE_BYTES, SkillPackageService
from app.transfer.package import export_filename

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _info(record: SkillRecord) -> SkillInfo:
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
        resource_count=record.resource_count,
        script_count=record.script_count,
    )


def _resource_info(record: SkillResourceRecord) -> SkillResourceInfo:
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


@router.post("/import/preview", response_model=SkillImportPreview)
async def preview_skill_import(
    file: UploadFile = File(...),
    service: SkillPackageService = Depends(get_skill_package_service),
) -> SkillImportPreview | JSONResponse:
    """解析上传的 zip 技能包并暂存预览（不落盘）。"""
    data = await file.read(MAX_PACKAGE_BYTES + 1)
    try:
        preview = await service.preview(data, filename=file.filename)
    except SkillPackageTooLargeError as exc:
        return _error(413, exc.error_type, str(exc))
    except SkillPackageError as exc:
        return _error(422, exc.error_type, str(exc))
    except SkillParseError as exc:
        return _error(422, exc.error_type, str(exc))

    package = preview.package
    return SkillImportPreview(
        token=preview.token,
        name=package.name,
        description=package.description,
        content=package.content,
        resources=[
            SkillPackageResource(name=item.name, content=item.content)
            for item in package.resources
        ],
        warnings=package.warnings,
        suggested_skill_id=package.suggested_skill_id,
        source_filename=package.source_filename,
        expires_in=int(service.ttl_seconds),
    )


@router.post("/import", response_model=SkillInfo)
async def confirm_skill_import(
    payload: SkillImportConfirm,
    service: SkillPackageService = Depends(get_skill_package_service),
) -> SkillInfo | JSONResponse:
    """确认导入（预览 token 一次性使用）。"""
    try:
        record = await service.confirm(payload.token)
    except SkillImportExpiredError as exc:
        return _error(409, exc.error_type, str(exc))
    return _info(record)


@router.get("/export", response_model=None)
async def export_all_skills(
    skill_service: SkillService = Depends(get_skill_service),
    service: SkillPackageService = Depends(get_skill_package_service),
) -> Response:
    """导出全部技能（zip：每项为标准 SKILL.md 目录 + manifest）。"""
    skills = await skill_service.list_skills()
    data = await service.export_collection(skills)
    filename = export_filename("skills", "zip")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{skill_id}/export", response_model=None)
async def export_skill(
    skill_id: str,
    service: SkillPackageService = Depends(get_skill_package_service),
) -> Response | JSONResponse:
    """导出标准技能包（SKILL.md + 标准附件，不含应用内部状态）。"""
    try:
        data = await service.export(skill_id)
    except SkillNotFoundError as exc:
        return _not_found(exc)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{skill_id}.zip"'},
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


@router.put("/{skill_id}/resources/{resource_id:path}", response_model=SkillResourceInfo)
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


@router.delete("/{skill_id}/resources/{resource_id:path}", response_model=None)
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
