"""DeepSeek Provider。

DeepSeek API 与 OpenAI Chat Completions 兼容，具体网络实现见
:class:`~app.llm.openai_compat.OpenAICompatProvider`，本文件只声明
DeepSeek 的协议标识、默认端点与默认模型。
"""

from __future__ import annotations

import httpx

from app.llm.openai_compat import OpenAICompatProvider

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


class DeepSeekProvider(OpenAICompatProvider):
    """DeepSeek（V4.1 Flash）Provider。"""

    name = "deepseek"
    display_name = "DeepSeek"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            api_key_env="DEEPSEEK_API_KEY",
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            transport=transport,
        )
