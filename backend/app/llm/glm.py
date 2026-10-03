"""GLM（智谱）Provider。

智谱开放平台提供 OpenAI Chat Completions 兼容接口
（默认 ``https://open.bigmodel.cn/api/paas/v4``），支持
``response_format={"type": "json_object"}`` 结构化输出，具体网络实现见
:class:`~app.llm.openai_compat.OpenAICompatProvider`。新增 Provider 不改
Agent Graph / State / RAG Tool（见 AGENTS.md §4.3 / §25）。
"""

from __future__ import annotations

import httpx

from app.llm.openai_compat import OpenAICompatProvider

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-5.3-flash"


class GLMProvider(OpenAICompatProvider):
    """智谱 GLM Provider。"""

    name = "glm"
    display_name = "GLM"

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
            api_key_env="GLM_API_KEY",
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            transport=transport,
        )
