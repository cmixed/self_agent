"""健康检查。不返回任何密钥或敏感配置。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.llm.factory import current_llm_provider, provider_configs
from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    active_provider = current_llm_provider()
    # 可用性按「配置表」判定，而不是按名字查环境变量：
    # UI 创建的自定义 Provider 的 id 是动态的（custom-xxxxxxxx），
    # 用名字匹配会一律判成"未配置密钥"（本地服务也会被误报要 API Key）。
    config = provider_configs(settings).get(active_provider)
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        llm_provider=active_provider,
        llm_configured=bool(config and config.available),
        llm_label=config.label if config else active_provider,
        llm_model=config.model if config else "",
        llm_local=bool(config and config.is_local),
    )
