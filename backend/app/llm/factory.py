"""LLM Provider 工厂。

业务代码通过 :func:`get_llm` 获取 Provider，不直接实例化具体实现。
支持 DeepSeek 与 GLM 两个 Provider（AGENTS.md §4.3/§25：新增 Provider
只需增加实现类与工厂分支，Agent Graph 不感知）。

运行时切换：:func:`switch_llm_provider` 原子地「先建新、后关旧」，
选择经 :class:`~app.core.provider_store.ProviderStore` 持久化，
``backend/.env`` 的 ``LLM_PROVIDER`` 仅作为首次启动默认值。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.provider_store import ProviderStore
from app.llm.base import LLMConfigError, LLMProvider
from app.llm.custom import CustomProvider
from app.llm.deepseek import DeepSeekProvider
from app.llm.glm import GLMProvider

logger = get_logger(__name__)

# 内置 Provider（来自 backend/.env）。自定义 Provider（UI 管理）在运行时并入，
# 见 provider_configs()。
BUILTIN_PROVIDERS: tuple[str, ...] = ("deepseek", "glm", "ollama", "custom")
# 向后兼容：旧代码/测试引用的名字
SUPPORTED_PROVIDERS = BUILTIN_PROVIDERS


@dataclass(frozen=True)
class ProviderConfig:
    """一个可用的 LLM 端点配置（内置与自定义共用同一结构）。

    P1 的条目全部来自 .env；P3 会把 SQLite 中的自定义条目也转成这个结构，
    因此工厂、切换逻辑、设置快照都不需要为两种来源各写一套。
    """

    id: str
    label: str
    base_url: str
    model: str
    api_key: str = ""
    api_key_env: str = "API_KEY"
    requires_api_key: bool = True
    is_local: bool = False
    timeout_seconds: float = 60.0
    max_retries: int = 2

    @property
    def available(self) -> bool:
        """是否具备调用条件（密钥就绪 / 本地服务无需密钥）。"""
        if not self.requires_api_key:
            return bool(self.base_url.strip() and self.model.strip())
        value = (self.api_key or "").strip()
        return bool(self.base_url.strip() and self.model.strip() and value)


def _secret(value) -> str:
    return value.get_secret_value().strip() if value is not None else ""


def provider_configs(settings: Settings) -> dict[str, ProviderConfig]:
    """全部可用 Provider（内置 + 自定义）。"""
    configs: dict[str, ProviderConfig] = {
        "deepseek": ProviderConfig(
            id="deepseek",
            label="DeepSeek",
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            api_key=_secret(settings.deepseek_api_key),
            api_key_env="DEEPSEEK_API_KEY",
            timeout_seconds=settings.deepseek_timeout_seconds,
            max_retries=settings.deepseek_max_retries,
        ),
        "glm": ProviderConfig(
            id="glm",
            label="GLM",
            base_url=settings.glm_base_url,
            model=settings.glm_model,
            api_key=_secret(settings.glm_api_key),
            api_key_env="GLM_API_KEY",
            timeout_seconds=settings.glm_timeout_seconds,
            max_retries=settings.glm_max_retries,
        ),
    }

    # Ollama：本地服务，无需密钥；未配置模型时不出现（避免界面出现不可用项）
    if settings.ollama_model.strip():
        configs["ollama"] = ProviderConfig(
            id="ollama",
            label="Ollama（本地）",
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            requires_api_key=False,
            is_local=True,
            timeout_seconds=settings.ollama_timeout_seconds,
            max_retries=settings.ollama_max_retries,
        )

    # 自定义 OpenAI 兼容端点（.env 版本；UI 版本在 P3 并入）
    if settings.custom_base_url.strip() or settings.custom_model.strip():
        configs["custom"] = ProviderConfig(
            id="custom",
            label=settings.custom_label.strip() or "自定义接口",
            base_url=settings.custom_base_url,
            model=settings.custom_model,
            api_key=_secret(settings.custom_api_key),
            api_key_env=settings.custom_api_key_env.strip() or "CUSTOM_API_KEY",
            requires_api_key=settings.custom_requires_api_key,
            is_local=settings.custom_is_local,
            timeout_seconds=settings.custom_timeout_seconds,
            max_retries=settings.custom_max_retries,
        )
    return configs

_provider: LLMProvider | None = None
_active_provider: str | None = None


def _normalize(name: str) -> str:
    return name.strip().lower()


def _validate_supported(name: str, settings: Settings) -> str:
    normalized = _normalize(name)
    if normalized not in provider_configs(settings):
        supported = "/".join(provider_configs(settings))
        raise LLMConfigError(f"不支持的 LLM Provider：{name}（可选：{supported}）")
    return normalized


def _build_provider(config: ProviderConfig) -> LLMProvider:
    """按配置构造 Provider；密钥缺失时抛出可读的 :class:`LLMConfigError`。"""
    if config.id == "deepseek":
        return DeepSeekProvider(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
        )
    if config.id == "glm":
        return GLMProvider(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
        )
    # Ollama 与自定义端点共用配置驱动的实现
    return CustomProvider(
        provider_id=config.id,
        label=config.label,
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        api_key_env=config.api_key_env,
        requires_api_key=config.requires_api_key,
        is_local=config.is_local,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
    )


def current_llm_provider() -> str:
    """返回当前生效的 Provider 名称（持久化选择 > 环境默认值）。"""
    global _active_provider
    if _active_provider is None:
        settings = get_settings()
        configs = provider_configs(settings)
        stored = ProviderStore(settings.settings_path).load()
        if stored in configs and configs[stored].available:
            _active_provider = stored
        else:
            _active_provider = _validate_supported(settings.llm_provider, settings)
    return _active_provider


def get_llm() -> LLMProvider:
    """返回进程级缓存的 Provider 实例。"""
    global _provider, _active_provider
    if _provider is None:
        settings = get_settings()
        name = current_llm_provider()
        config = provider_configs(settings).get(name)
        if config is None:
            raise LLMConfigError(f"不支持的 LLM Provider：{name}")
        if not config.available:
            raise LLMConfigError(f"{config.api_key_env} 未配置")
        _provider = _build_provider(config)
        _active_provider = name
    return _provider


async def switch_llm_provider(name: str) -> str:
    """运行时切换 Provider：先建新、后关旧，失败不影响现有实例。

    返回切换后的 Provider 名称；选择持久化到 ``settings_path``（写失败仅
    记录警告，本次进程内切换仍然生效）。
    """
    global _provider, _active_provider
    settings = get_settings()
    target = _validate_supported(name, settings)

    config = provider_configs(settings).get(target)
    if config is None or not config.available:
        env_key = config.api_key_env if config is not None else "API_KEY"
        raise LLMConfigError(f"{env_key} 未配置，无法切换到 {target}")

    if _provider is not None and _active_provider == target:
        return target

    new_provider = _build_provider(config)
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
