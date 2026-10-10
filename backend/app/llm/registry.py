"""自定义 Provider 的内存注册表。

工厂（`provider_configs` / `get_llm`）是**同步**调用，而配置存在 SQLite。
因此：启动时装载一次，之后由 ProviderService 在增删改后刷新；
工厂只读内存，不碰数据库（避免同步阻塞事件循环，见 AGENTS.md §11 的性能约定）。
"""

from __future__ import annotations

from app.llm.provider_config import ProviderConfig

_custom_configs: dict[str, ProviderConfig] = {}


def set_custom_providers(configs: list[ProviderConfig]) -> None:
    """整体替换自定义 Provider（由服务层在变更后调用）。"""
    _custom_configs.clear()
    for config in configs:
        _custom_configs[config.id] = config


def custom_provider_configs() -> dict[str, ProviderConfig]:
    return dict(_custom_configs)


def reset_custom_providers() -> None:
    _custom_configs.clear()
