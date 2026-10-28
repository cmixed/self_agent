"""长期记忆接口（AGENTS.md §14）。

- ``GET    /api/memory``                       查看偏好与记忆
- ``PUT    /api/memory/preferences/{key}``      设置偏好
- ``DELETE /api/memory/preferences/{key}``      删除偏好
- ``POST   /api/memory/memories``               新增记忆
- ``DELETE /api/memory/memories/{memory_id}``   删除记忆
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, Response

from app.api.deps import get_memory_package_service, get_memory_service, get_user_id
from app.core.logging import get_logger
from app.models.schemas import (
    AddMemoryRequest,
    ErrorResponse,
    ImportConfirmRequest,
    MemoryImportPreview,
    MemoryImportResultOut,
    MemoryOut,
    MemoryPackageItemOut,
    MemoryProfileResponse,
    SetPreferenceRequest,
)
from app.services.memory_package_service import MAX_PACKAGE_BYTES, MemoryPackageService
from app.services.memory_service import MemoryService
from app.transfer.errors import (
    ImportPackageError,
    ImportPackageTooLargeError,
    ImportPreviewExpiredError,
)
from app.transfer.package import export_filename

router = APIRouter(prefix="/api/memory", tags=["memory"])
logger = get_logger(__name__)


@router.get("", response_model=MemoryProfileResponse)
async def get_memory(
    service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> MemoryProfileResponse:
    preferences, memories = await service.get_profile(user_id)
    return MemoryProfileResponse(
        user_id=user_id,
        preferences=preferences,
        memories=[MemoryOut.model_validate(memory.__dict__) for memory in memories],
    )


def _import_error(status_code: int, error_type: str, detail: str) -> JSONResponse:
    body = ErrorResponse(error=error_type, error_type=error_type, detail=detail)
    return JSONResponse(status_code=status_code, content=body.model_dump())


@router.get("/export", response_model=None)
async def export_memory(
    service: MemoryPackageService = Depends(get_memory_package_service),
    user_id: str = Depends(get_user_id),
) -> Response:
    """导出当前用户的偏好与长期记忆（JSON）。"""
    data = await service.export_all(user_id)
    filename = export_filename("memory", "json")
    return Response(
        content=data,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import/preview", response_model=MemoryImportPreview)
async def preview_memory_import(
    file: UploadFile = File(...),
    service: MemoryPackageService = Depends(get_memory_package_service),
    user_id: str = Depends(get_user_id),
) -> MemoryImportPreview | JSONResponse:
    data = await file.read(MAX_PACKAGE_BYTES + 1)
    try:
        token, preview = await service.preview(user_id, data, filename=file.filename)
    except ImportPackageTooLargeError as exc:
        return _import_error(413, exc.error_type, exc.message)
    except ImportPackageError as exc:
        return _import_error(422, exc.error_type, exc.message)

    return MemoryImportPreview(
        token=token,
        preferences=preview.preferences,
        memories=[
            MemoryPackageItemOut(kind=item.kind, content=item.content) for item in preview.memories
        ],
        skipped_preferences=preview.skipped_preferences,
        skipped_memories=preview.skipped_memories,
        warnings=preview.warnings,
        source_filename=preview.source_filename,
        expires_in=int(service.ttl_seconds),
    )


@router.post("/import", response_model=MemoryImportResultOut)
async def confirm_memory_import(
    payload: ImportConfirmRequest,
    service: MemoryPackageService = Depends(get_memory_package_service),
    user_id: str = Depends(get_user_id),
) -> MemoryImportResultOut | JSONResponse:
    try:
        result = await service.confirm(user_id, payload.token)
    except ImportPreviewExpiredError as exc:
        return _import_error(409, exc.error_type, exc.message)
    return MemoryImportResultOut(
        preferences=result.preferences,
        memories=result.memories,
        skipped_preferences=result.skipped_preferences,
        skipped_memories=result.skipped_memories,
    )


@router.put("/preferences/{key}", response_model=MemoryProfileResponse)
async def set_preference(
    key: str,
    payload: SetPreferenceRequest,
    service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> MemoryProfileResponse:
    await service.set_preference(user_id, key, payload.value)
    return await get_memory(service=service, user_id=user_id)


@router.delete("/preferences/{key}", response_model=MemoryProfileResponse)
async def delete_preference(
    key: str,
    service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> MemoryProfileResponse:
    if not await service.delete_preference(user_id, key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="偏好不存在")
    return await get_memory(service=service, user_id=user_id)


@router.post("/memories", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def add_memory(
    payload: AddMemoryRequest,
    service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> MemoryOut:
    record = await service.add_memory(
        user_id,
        kind=payload.kind,
        content=payload.content,
        source_task_id=payload.source_task_id,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="相同或高度相似的记忆已存在"
        )
    return MemoryOut.model_validate(record.__dict__)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: int,
    service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> None:
    if not await service.delete_memory(user_id, memory_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记忆不存在")
