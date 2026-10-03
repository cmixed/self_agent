"""预设任务 API：工作台快捷任务的增删改查。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_preset_service
from app.models.schemas import (
    ErrorResponse,
    PresetCreate,
    PresetInfo,
    PresetListResponse,
    PresetUpdate,
)
from app.services.preset_service import PresetNotFoundError, PresetService

router = APIRouter(prefix="/api/presets", tags=["presets"])


def _info(record) -> PresetInfo:
    return PresetInfo(
        preset_id=record.preset_id,
        title=record.title,
        description=record.description,
        query=record.query,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _not_found(exc: PresetNotFoundError) -> JSONResponse:
    body = ErrorResponse(error="preset_not_found", error_type="preset_not_found", detail=str(exc))
    return JSONResponse(status_code=404, content=body.model_dump())


@router.get("", response_model=PresetListResponse)
async def list_presets(
    service: PresetService = Depends(get_preset_service),
) -> PresetListResponse:
    return PresetListResponse(presets=[_info(record) for record in await service.list_presets()])


@router.post("", response_model=PresetInfo)
async def create_preset(
    payload: PresetCreate, service: PresetService = Depends(get_preset_service)
) -> PresetInfo:
    record = await service.create_preset(
        title=payload.title, description=payload.description, query=payload.query
    )
    return _info(record)


@router.put("/{preset_id}", response_model=PresetInfo)
async def update_preset(
    preset_id: str,
    payload: PresetUpdate,
    service: PresetService = Depends(get_preset_service),
) -> PresetInfo | JSONResponse:
    try:
        record = await service.update_preset(
            preset_id,
            title=payload.title,
            description=payload.description,
            query=payload.query,
        )
    except PresetNotFoundError as exc:
        return _not_found(exc)
    return _info(record)


@router.delete("/{preset_id}", response_model=None)
async def delete_preset(
    preset_id: str, service: PresetService = Depends(get_preset_service)
) -> dict[str, str] | JSONResponse:
    try:
        await service.delete_preset(preset_id)
    except PresetNotFoundError as exc:
        return _not_found(exc)
    return {"status": "deleted"}
