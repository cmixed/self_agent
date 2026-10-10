"""模型服务管理 API：连通性测试与模型发现（§18）。

- 由后端代理访问端点：浏览器不直连、密钥不落地到前端；
- 只允许 http/https；本地地址（127.0.0.1 / localhost）是 Ollama 的必要场景。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.llm.factory import provider_configs
from app.llm.probe import list_remote_models, probe_chat
from app.models.schemas import (
    ErrorResponse,
    ModelListResponse,
    ProviderProbeRequest,
    ProviderProbeResponse,
)

router = APIRouter(prefix="/api/providers", tags=["providers"])

_ALLOWED_SCHEMES = ("http://", "https://")


def _invalid_url(base_url: str) -> JSONResponse | None:
    if not base_url.strip().startswith(_ALLOWED_SCHEMES):
        body = ErrorResponse(
            error="invalid_base_url",
            error_type="invalid_base_url",
            detail="接口地址必须以 http:// 或 https:// 开头",
        )
        return JSONResponse(status_code=400, content=body.model_dump())
    return None


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    base_url: str, provider_id: str | None = None
) -> ModelListResponse | JSONResponse:
    """列出端点可用模型；给了 provider_id 就用该 Provider 的服务端密钥。"""
    if (bad := _invalid_url(base_url)) is not None:
        return bad

    api_key = ""
    if provider_id:
        config = provider_configs(get_settings()).get(provider_id)
        if config is not None:
            api_key = config.api_key

    result = await list_remote_models(base_url=base_url, api_key=api_key)
    return ModelListResponse(
        ok=result.ok, detail=result.detail, models=result.models or [], latency_ms=result.latency_ms
    )


@router.post("/test", response_model=ProviderProbeResponse)
async def test_provider(payload: ProviderProbeRequest) -> ProviderProbeResponse | JSONResponse:
    """测试「地址 + 模型 + 密钥」是否可用（会真实发一条极小请求）。"""
    if (bad := _invalid_url(payload.base_url)) is not None:
        return bad

    api_key = payload.api_key or ""
    label_env = "API_KEY"
    requires_api_key = payload.requires_api_key
    is_local = payload.is_local
    timeout_seconds = payload.timeout_seconds

    if payload.provider_id:
        # 已保存的 Provider：密钥只看服务端配置，前端传什么都不用
        config = provider_configs(get_settings()).get(payload.provider_id)
        if config is not None:
            api_key = config.api_key or api_key
            label_env = config.api_key_env
            requires_api_key = config.requires_api_key
            is_local = config.is_local
            timeout_seconds = min(config.timeout_seconds, payload.timeout_seconds)

    result = await probe_chat(
        base_url=payload.base_url,
        model=payload.model,
        api_key=api_key,
        api_key_env=label_env,
        requires_api_key=requires_api_key,
        is_local=is_local,
        timeout_seconds=timeout_seconds,
    )
    return ProviderProbeResponse(
        ok=result.ok,
        detail=result.detail,
        latency_ms=result.latency_ms,
        reply=result.reply,
    )
