"""LLM Provider 工厂。

业务代码通过 :func:`get_llm` 获取 Provider，不直接实例化具体实现。
支持 DeepSeek 与 GLM 两个 Provider（AGENTS.md §4.3/§25：新增 Provider
只需增加实现类与工厂分支，Agent Graph 不感知）。

运行时切换：:func:`switch_llm_provider` 原子地「先建新、后关旧」，
选择经 :class:`~app.core.provider_store.ProviderStore` 持久化，
``backend/.env`` 的 ``LLM_PROVIDER`` 仅作为首次启动默认值。
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.provider_store import ProviderStore
from app.llm.base import LLMConfigError, LLMProvider
from app.llm.deepseek import DeepSeekProvider
from app.llm.glm import GLMProvider

logger = get_logger(__name__)

SUPPORTED_PROVIDERS: tuple[str, ...] = ("deepseek", "glm")

_provider: LLMProvider | None = None
_active_provider: str | None = None


def _normalize(name: str) -> str:
    return name.strip().lower()


def _validate_supported(name: str) -> str:
    normalized = _normalize(name)
    if normalized not in SUPPORTED_PROVIDERS:
        supported = "/".join(SUPPORTED_PROVIDERS)
        raise LLMConfigError(f"不支持的 LLM Provider：{name}（可选：{supported}）")
    return normalized


def _build_provider(settings: Settings, name: str) -> LLMProvider:
    """按名称构造 Provider；密钥缺失时抛出可读的 :class:`LLMConfigError`。"""
    if name == "deepseek":
        api_key = (
            settings.deepseek_api_key.get_secret_value().strip()
            if settings.deepseek_api_key is not None
            else ""
        )
        if not api_key:
            raise LLMConfigError("DEEPSEEK_API_KEY 未配置")
        return DeepSeekProvider(
            api_key=api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout_seconds=settings.deepseek_timeout_seconds,
            max_retries=settings.deepseek_max_retries,
        )
    if name == "glm":
        api_key = (
            settings.glm_api_key.get_secret_value().strip()
            if settings.glm_api_key is not None
            else ""
        )
        if not api_key:
            raise LLMConfigError("GLM_API_KEY 未配置")
        return GLMProvider(
            api_key=api_key,
            base_url=settings.glm_base_url,
            model=settings.glm_model,
            timeout_seconds=settings.glm_timeout_seconds,
            max_retries=settings.glm_max_retries,
        )
    supported = "/".join(SUPPORTED_PROVIDERS)
    raise LLMConfigError(f"不支持的 LLM Provider：{name}（可选：{supported}）")


def current_llm_provider() -> str:
    """返回当前生效的 Provider 名称（持久化选择 > 环境默认值）。"""
    global _active_provider
    if _active_provider is None:
        settings = get_settings()
        stored = ProviderStore(settings.settings_path).load()
        if stored in SUPPORTED_PROVIDERS and settings.provider_configured(stored):
            _active_provider = stored
        else:
            _active_provider = _validate_supported(settings.llm_provider)
    return _active_provider


def get_llm() -> LLMProvider:
    """返回进程级缓存的 Provider 实例。"""
    global _provider, _active_provider
    if _provider is None:
        settings = get_settings()
        name = current_llm_provider()
        _provider = _build_provider(settings, name)
        _active_provider = name
    return _provider


async def switch_llm_provider(name: str) -> str:
    """运行时切换 Provider：先建新、后关旧，失败不影响现有实例。

    返回切换后的 Provider 名称；选择持久化到 ``settings_path``（写失败仅
    记录警告，本次进程内切换仍然生效）。
    """
    global _provider, _active_provider
    target = _validate_supported(name)

    settings = get_settings()
    if not settings.provider_configured(target):
        env_key = "DEEPSEEK_API_KEY" if target == "deepseek" else "GLM_API_KEY"
        raise LLMConfigError(f"{env_key} 未配置，无法切换到 {target}")

    if _provider is not None and _active_provider == target:
        return target

    new_provider = _build_provider(settings, target)
    old_provider = _provider
    _provider = new_provider
    _active_provider = target
    if old_provider is not None:
        await old_provider.aclose()

    try:
        ProviderStore(settings.settings_path).save(target)
    except OSError as exc:
        logger.warning(
            f"Provider 选择持久化失败（本次进程内仍生效）：{exc}",
            extra={"event": "provider_persist_failed", "status": "error"},
        )
    logger.info(
        f"LLM Provider 已切换为 {target}",
        extra={"event": "provider_switched", "status": "ok", "node": target},
    )
    return target


async def close_llm() -> None:
    """关闭并清空缓存的 Provider（应用关闭时调用）。"""
    global _provider
    if _provider is not None:
        await _provider.aclose()
        _provider = None


def reset_llm() -> None:
    """仅用于测试：清空缓存与激活名称，不关闭底层连接。"""
    global _provider, _active_provider
    _provider = None
    _active_provider = None
