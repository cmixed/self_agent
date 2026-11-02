"""预设任务 API：工作台快捷任务的增删改查。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse, Response

from app.api.deps import get_preset_package_service, get_preset_service
from app.models.schemas import (
    ErrorResponse,
    ImportConfirmRequest,
    OutputMode,
    PresetCreate,
    PresetImportItem,
    PresetImportPreview,
    PresetImportResult,
    PresetInfo,
    PresetListResponse,
    PresetOrderRequest,
    PresetUpdate,
    TaskScope,
)
from app.services.preset_package_service import MAX_PACKAGE_BYTES, PresetPackageService
from app.services.preset_service import (
    PresetNotFoundError,
    PresetOrderError,
    PresetService,
)
from app.transfer.errors import (
    ImportPackageError,
    ImportPackageTooLargeError,
    ImportPreviewExpiredError,
)
from app.transfer.package import export_filename

router = APIRouter(prefix="/api/presets", tags=["presets"])


def _scope_of(record) -> TaskScope | None:
    """范围两者皆空 = 未绑定，返回 None。"""
    if not record.category_ids and not record.document_ids:
        return None
    return TaskScope(category_ids=list(record.category_ids), document_ids=list(record.document_ids))


def _info(record) -> PresetInfo:
    return PresetInfo(
        preset_id=record.preset_id,
        title=record.title,
        description=record.description,
        query=record.query,
        output_mode=record.output_mode,  # type: ignore[arg-type]
        scope=_scope_of(record),
        auto_run=record.auto_run,
        sort_order=record.sort_order,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _not_found(exc: PresetNotFoundError) -> JSONResponse:
    body = ErrorResponse(error="preset_not_found", error_type="preset_not_found", detail=str(exc))
    return JSONResponse(status_code=404, content=body.model_dump())


def _order_conflict(exc: PresetOrderError) -> JSONResponse:
    body = ErrorResponse(
        error="preset_order_conflict",
        error_type="preset_order_conflict",
        detail=str(exc),
    )
    return JSONResponse(status_code=409, content=body.model_dump())


def _error(status: int, error_type: str, detail: str) -> JSONResponse:
    body = ErrorResponse(error=error_type, error_type=error_type, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump())


def _package_item(item) -> PresetImportItem:
    return PresetImportItem(
        title=item.title,
        description=item.description,
        query=item.query,
        output_mode=item.output_mode,  # type: ignore[arg-type]
        auto_run=item.auto_run,
        scope=(
            TaskScope(category_ids=list(item.category_ids), document_ids=list(item.document_ids))
            if item.category_ids or item.document_ids
            else None
        ),
    )


@router.get("", response_model=PresetListResponse)
async def list_presets(
    output_mode: OutputMode | None = Query(default=None),
    service: PresetService = Depends(get_preset_service),
) -> PresetListResponse:
    """列出预设；``output_mode`` 为空时返回两种模式的全部预设。"""
    return PresetListResponse(
        presets=[_info(record) for record in await service.list_presets(output_mode)]
    )


@router.get("/export", response_model=None)
async def export_presets(
    service: PresetPackageService = Depends(get_preset_package_service),
) -> Response:
    """导出全部预设（JSON；顺序即工作台展示顺序）。"""
    data = await service.export_all()
    filename = export_filename("presets", "json")
    return Response(
        content=data,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import/preview", response_model=PresetImportPreview)
async def preview_preset_import(
    file: UploadFile = File(...),
    service: PresetPackageService = Depends(get_preset_package_service),
) -> PresetImportPreview | JSONResponse:
    data = await file.read(MAX_PACKAGE_BYTES + 1)
    try:
        token, preview = await service.preview(data, filename=file.filename)
    except ImportPackageTooLargeError as exc:
        return _error(413, exc.error_type, exc.message)
    except ImportPackageError as exc:
        return _error(422, exc.error_type, exc.message)

    return PresetImportPreview(
        token=token,
        presets=[_package_item(item) for item in preview.items],
        skipped_duplicates=preview.skipped,
        warnings=preview.warnings,
        source_filename=preview.source_filename,
        expires_in=int(service.ttl_seconds),
    )


@router.post("/import", response_model=PresetImportResult)
async def confirm_preset_import(
    payload: ImportConfirmRequest,
    service: PresetPackageService = Depends(get_preset_package_service),
) -> PresetImportResult | JSONResponse:
    try:
        imported, skipped = await service.confirm(payload.token)
    except ImportPreviewExpiredError as exc:
        return _error(409, exc.error_type, exc.message)
    return PresetImportResult(
        imported=[_info(record) for record in imported],
        skipped=skipped,
    )


@router.post("", response_model=PresetInfo)
async def create_preset(
    payload: PresetCreate, service: PresetService = Depends(get_preset_service)
) -> PresetInfo:
    record = await service.create_preset(
        title=payload.title,
        description=payload.description,
        query=payload.query,
        output_mode=payload.output_mode,
        category_ids=list(payload.scope.category_ids) if payload.scope else None,
        document_ids=list(payload.scope.document_ids) if payload.scope else None,
        auto_run=payload.auto_run,
    )
    return _info(record)


@router.put("/order", response_model=PresetListResponse)
async def reorder_presets(
    payload: PresetOrderRequest, service: PresetService = Depends(get_preset_service)
) -> PresetListResponse | JSONResponse:
    """按同一输出方式内的完整 id 列表重排工作台预设。"""
    try:
        presets = await service.reorder_presets(
            list(payload.preset_ids), output_mode=payload.output_mode
        )
    except PresetOrderError as exc:
        return _order_conflict(exc)
    return PresetListResponse(presets=[_info(record) for record in presets])


@router.put("/{preset_id}", response_model=PresetInfo)
async def update_preset(
    preset_id: str,
    payload: PresetUpdate,
    service: PresetService = Depends(get_preset_service),
) -> PresetInfo | JSONResponse:
    try:
        # scope 用 model_fields_set 判定「是否提供」：`null` 是合法值（清除绑定范围）
        scope_provided = "scope" in payload.model_fields_set
        record = await service.update_preset(
            preset_id,
            title=payload.title,
            description=payload.description,
            query=payload.query,
            category_ids=(
                (list(payload.scope.category_ids) if payload.scope else [])
                if scope_provided
                else None
            ),
            document_ids=(
                (list(payload.scope.document_ids) if payload.scope else [])
                if scope_provided
                else None
            ),
            auto_run=payload.auto_run,
            output_mode=payload.output_mode,
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
