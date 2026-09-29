"""LLM Provider 工厂。

业务代码通过 :func:`get_llm` 获取 Provider，不直接实例化具体实现。
Phase 1 只支持 DeepSeek；Ollama 属于后续阶段，届时只需在此处增加分支。
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.llm.base import LLMConfigError, LLMProvider
from app.llm.deepseek import DeepSeekProvider

_provider: LLMProvider | None = None


def _create_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider.strip().lower()

    if provider == "deepseek":
        if settings.deepseek_api_key is None:
            raise LLMConfigError("DEEPSEEK_API_KEY 未配置")
        return DeepSeekProvider(
            api_key=settings.deepseek_api_key.get_secret_value(),
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout_seconds=settings.deepseek_timeout_seconds,
            max_retries=settings.deepseek_max_retries,
        )

    raise LLMConfigError(f"不支持的 LLM_PROVIDER：{settings.llm_provider}")


def get_llm() -> LLMProvider:
    """返回进程级缓存的 Provider 实例。"""
    global _provider
    if _provider is None:
        _provider = _create_provider(get_settings())
    return _provider


async def close_llm() -> None:
    """关闭并清空缓存的 Provider（应用关闭时调用）。"""
    global _provider
    if _provider is not None:
        await _provider.aclose()
        _provider = None


def reset_llm() -> None:
    """仅用于测试：清空缓存，不关闭底层连接。"""
    global _provider
    _provider = None
