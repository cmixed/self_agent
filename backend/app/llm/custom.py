"""自定义 / 本地 OpenAI 兼容 Provider。

用户可以在 UI 里新增任意 OpenAI 兼容端点（Kimi、Ollama、vLLM、LM Studio…），
它们与 DeepSeek/GLM 走同一个客户端实现，只是配置不同：

- ``requires_api_key=False``：本地服务无需密钥（不发 Authorization 头）；
- ``is_local=True``：用于错误提示（本地服务未启动 vs 上游异常）与默认长超时；
- 端点若不支持 ``response_format``，客户端会自动回退为纯提示词 JSON 模式。
"""

from __future__ import annotations

import httpx

from app.llm.openai_compat import OpenAICompatProvider


class CustomProvider(OpenAICompatProvider):
    """配置驱动的 OpenAI 兼容 Provider（id / 名称由配置决定）。"""

    name = "custom"
    display_name = "自定义接口"

    def __init__(
        self,
        *,
        provider_id: str,
        label: str,
        api_key: str,
        base_url: str,
        model: str,
        api_key_env: str = "CUSTOM_API_KEY",
        requires_api_key: bool = True,
        is_local: bool = False,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # 实例级 name/display_name：API 与切换逻辑按 id 识别，错误信息用 label
        self.name = provider_id
        self.display_name = label or provider_id
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            api_key_env=api_key_env,
            requires_api_key=requires_api_key,
            is_local=is_local,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            transport=transport,
        )
