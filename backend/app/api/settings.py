"""应用设置：查看与运行时切换 LLM Provider。

- ``GET /api/settings`` 返回各 Provider 的配置状态快照（不含密钥）；
- ``PUT /api/settings/llm-provider`` 切换当前 Provider，立即生效并持久化。

切换目标未配置密钥时返回 409 + 可读错误（统一错误体结构），
不支持自动降级，由用户决定下一步（见 AGENTS.md §20）。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.llm.base import LLMConfigError
from app.llm.factory import (
    current_llm_provider,
    provider_configs,
    switch_llm_provider,
)
from app.models.schemas import ErrorResponse, LLMProviderInfo, LlmProviderUpdate, SettingsResponse

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _snapshot() -> SettingsResponse:
    """全部可切换的 Provider（内置 + 自定义/本地；未配置完备的不出现）。

    内置两项即使未配置密钥也保留（界面显示为"未配置"并禁用），
    可选扩展（Ollama / 自定义）只在配置了端点与模型后才出现。
    """
    settings = get_settings()
    active = current_llm_provider()
    configs = provider_configs(settings)
    ordered = ["deepseek", "glm", *[name for name in configs if name not in {"deepseek", "glm"}]]
    providers = [
        LLMProviderInfo(
            id=name,
            model=configs[name].model,
            configured=configs[name].available,
            active=name == active,
            label=configs[name].label,
            base_url=configs[name].base_url,
            is_local=configs[name].is_local,
            managed=configs[name].managed,
            key_source=configs[name].key_source,
            key_hint=configs[name].key_hint,
        )
        for name in ordered
        if name in configs
    ]
    return SettingsResponse(llm_provider=active, providers=providers)


@router.get("", response_model=SettingsResponse)
async def get_app_settings() -> SettingsResponse:
    return _snapshot()


@router.put("/llm-provider", response_model=SettingsResponse)
async def update_llm_provider(payload: LlmProviderUpdate) -> SettingsResponse | JSONResponse:
    if payload.provider.strip().lower() not in provider_configs(get_settings()):
        body = ErrorResponse(
            error="unknown_provider",
            error_type="unknown_provider",
            detail=f"不支持的 LLM Provider：{payload.provider}",
        )
        return JSONResponse(status_code=422, content=body.model_dump())
    try:
        await switch_llm_provider(payload.provider)
    except LLMConfigError as exc:
        # 409：当前配置状态不允许切换；detail 为可读原因，不泄露密钥
        body = ErrorResponse(error=exc.error_type, error_type=exc.error_type, detail=exc.message)
        return JSONResponse(status_code=409, content=body.model_dump())
    return _snapshot()
