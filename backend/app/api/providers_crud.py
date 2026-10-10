"""自定义 LLM Provider 的 CRUD（UI「模型服务」页）。

密钥只进不出：响应里只有 ``key_source``（env/db/none）与 ``key_hint``（末 4 位）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_provider_service
from app.models.schemas import (
    ErrorResponse,
    ProviderCreateRequest,
    ProviderListResponse,
    ProviderResponse,
    ProviderUpdateRequest,
)
from app.services.provider_service import (
    ProviderNotFoundError,
    ProviderService,
    ProviderValidationError,
    ProviderView,
)

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _response(view: ProviderView) -> ProviderResponse:
    return ProviderResponse(
        provider_id=view.provider_id,
        label=view.label,
        base_url=view.base_url,
        model=view.model,
        api_key_env=view.api_key_env,
        key_source=view.key_source,
        key_hint=view.key_hint,
        requires_api_key=view.requires_api_key,
        is_local=view.is_local,
        timeout_seconds=view.timeout_seconds,
        max_retries=view.max_retries,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _error(status: int, error_type: str, detail: str) -> JSONResponse:
    body = ErrorResponse(error=error_type, error_type=error_type, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump())


@router.get("", response_model=ProviderListResponse)
async def list_providers(
    service: ProviderService = Depends(get_provider_service),
) -> ProviderListResponse:
    return ProviderListResponse(providers=[_response(v) for v in await service.list_providers()])


@router.post("", response_model=ProviderResponse)
async def create_provider(
    payload: ProviderCreateRequest, service: ProviderService = Depends(get_provider_service)
) -> ProviderResponse | JSONResponse:
    try:
        view = await service.create_provider(
            label=payload.label or "",
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key or "",
            api_key_env=payload.api_key_env or "",
            requires_api_key=payload.requires_api_key,
            is_local=payload.is_local,
            timeout_seconds=payload.timeout_seconds,
            max_retries=payload.max_retries,
        )
    except ProviderValidationError as exc:
        return _error(400, "invalid_provider", str(exc))
    return _response(view)


@router.put("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str,
    payload: ProviderUpdateRequest,
    service: ProviderService = Depends(get_provider_service),
) -> ProviderResponse | JSONResponse:
    try:
        view = await service.update_provider(
            provider_id,
            label=payload.label,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
            api_key_env=payload.api_key_env,
            requires_api_key=payload.requires_api_key,
            is_local=payload.is_local,
            timeout_seconds=payload.timeout_seconds,
            max_retries=payload.max_retries,
        )
    except ProviderNotFoundError as exc:
        return _error(404, "provider_not_found", str(exc))
    except ProviderValidationError as exc:
        return _error(400, "invalid_provider", str(exc))
    return _response(view)


@router.delete("/{provider_id}", response_model=None)
async def delete_provider(
    provider_id: str, service: ProviderService = Depends(get_provider_service)
) -> dict[str, str] | JSONResponse:
    try:
        await service.delete_provider(provider_id)
    except ProviderNotFoundError as exc:
        return _error(404, "provider_not_found", str(exc))
    return {"status": "deleted", "provider_id": provider_id}
