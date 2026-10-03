"""健康检查。不返回任何密钥或敏感配置。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.llm.factory import current_llm_provider
from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    active_provider = current_llm_provider()
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        llm_provider=active_provider,
        llm_configured=settings.provider_configured(active_provider),
    )
