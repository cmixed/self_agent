"""系统级一键备份 / 恢复 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response

from app.api.deps import get_backup_service, get_user_id
from app.core.logging import get_logger
from app.models.schemas import (
    BackupImportPreview,
    BackupImportResult,
    BackupSectionPreviewOut,
    BackupSectionResultOut,
    ErrorResponse,
    ImportConfirmRequest,
)
from app.services.backup_service import MAX_PACKAGE_BYTES, BackupService
from app.transfer.errors import (
    ImportPackageError,
    ImportPackageTooLargeError,
    ImportPreviewExpiredError,
)
from app.transfer.package import export_filename

router = APIRouter(prefix="/api/backup", tags=["backup"])
logger = get_logger(__name__)


def _error(status: int, error_type: str, detail: str) -> JSONResponse:
    body = ErrorResponse(error=error_type, error_type=error_type, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump())


@router.get("/export", response_model=None)
async def export_backup(
    service: BackupService = Depends(get_backup_service),
    user_id: str = Depends(get_user_id),
) -> Response | JSONResponse:
    """导出全部可迁移数据（知识库 + 预设 + 长期记忆 + 自定义技能）。"""
    try:
        data = await service.export_all(user_id)
    except Exception as exc:
        logger.warning(
            "一键备份导出失败",
            extra={
                "event": "backup_export_failed",
                "status": "error",
                "error_type": type(exc).__name__,
            },
        )
        return _error(
            502,
            "backup_export_failed",
            "导出备份失败：请确认知识库与技能目录可读后重试",
        )
    filename = export_filename("self-agent-backup", "zip")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import/preview", response_model=BackupImportPreview)
async def preview_backup_import(
    file: UploadFile = File(...),
    service: BackupService = Depends(get_backup_service),
    user_id: str = Depends(get_user_id),
) -> BackupImportPreview | JSONResponse:
    data = await file.read(MAX_PACKAGE_BYTES + 1)
    try:
        token, preview = await service.preview(user_id, data, filename=file.filename)
    except ImportPackageTooLargeError as exc:
        return _error(413, exc.error_type, exc.message)
    except ImportPackageError as exc:
        return _error(422, exc.error_type, exc.message)

    return BackupImportPreview(
        token=token,
        sections=[
            BackupSectionPreviewOut(
                key=item.key,
                label=item.label,
                summary=item.summary,
                warnings=item.warnings,
            )
            for item in preview.sections
        ],
        warnings=preview.warnings,
        source_filename=preview.source_filename,
        expires_in=int(service.ttl_seconds),
    )


@router.post("/import", response_model=BackupImportResult)
async def confirm_backup_import(
    payload: ImportConfirmRequest,
    service: BackupService = Depends(get_backup_service),
    user_id: str = Depends(get_user_id),
) -> BackupImportResult | JSONResponse:
    try:
        result = await service.confirm(user_id, payload.token)
    except ImportPreviewExpiredError as exc:
        return _error(409, exc.error_type, exc.message)
    except Exception as exc:  # pragma: no cover - 兜底，分域错误已在 service 内聚合
        logger.warning(
            "一键恢复失败",
            extra={
                "event": "backup_import_failed",
                "status": "error",
                "error_type": type(exc).__name__,
            },
        )
        return _error(502, "backup_import_failed", "恢复备份失败，请重新上传后重试")

    return BackupImportResult(
        sections=[
            BackupSectionResultOut(
                key=item.key,
                label=item.label,
                summary=item.summary,
                failed=item.failed,
            )
            for item in result.sections
        ],
        warnings=result.warnings,
    )
