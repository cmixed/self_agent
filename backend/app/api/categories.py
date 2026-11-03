"""知识库类别 API（多标签组织）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_category_service
from app.models.schemas import (
    CategoryCreate,
    CategoryInfo,
    CategoryListResponse,
    CategoryUpdate,
    ErrorResponse,
)
from app.services.category_service import (
    CategoryNameConflictError,
    CategoryNotFoundError,
    CategoryService,
)

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _info(record) -> CategoryInfo:
    return CategoryInfo(
        category_id=record.category_id,
        name=record.name,
        description=record.description,
        document_count=record.document_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _error(status: int, error_type: str, detail: str) -> JSONResponse:
    body = ErrorResponse(error=error_type, error_type=error_type, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump())


@router.get("", response_model=CategoryListResponse)
async def list_categories(
    service: CategoryService = Depends(get_category_service),
) -> CategoryListResponse:
    return CategoryListResponse(
        categories=[_info(record) for record in await service.list_categories()]
    )


@router.post("", response_model=CategoryInfo)
async def create_category(
    payload: CategoryCreate, service: CategoryService = Depends(get_category_service)
) -> CategoryInfo | JSONResponse:
    try:
        record = await service.create_category(name=payload.name, description=payload.description)
    except CategoryNameConflictError as exc:
        return _error(409, "category_name_conflict", str(exc))
    return _info(record)


@router.put("/{category_id}", response_model=CategoryInfo)
async def update_category(
    category_id: str,
    payload: CategoryUpdate,
    service: CategoryService = Depends(get_category_service),
) -> CategoryInfo | JSONResponse:
    try:
        record = await service.update_category(
            category_id, name=payload.name, description=payload.description
        )
    except CategoryNotFoundError as exc:
        return _error(404, "category_not_found", str(exc))
    except CategoryNameConflictError as exc:
        return _error(409, "category_name_conflict", str(exc))
    return _info(record)


@router.delete("/{category_id}", response_model=None)
async def delete_category(
    category_id: str, service: CategoryService = Depends(get_category_service)
) -> dict[str, str] | JSONResponse:
    try:
        await service.delete_category(category_id)
    except CategoryNotFoundError as exc:
        return _error(404, "category_not_found", str(exc))
    return {"status": "deleted"}
