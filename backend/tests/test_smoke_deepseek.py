"""真实 DeepSeek API 冒烟测试。

默认被排除（pyproject 中 ``addopts = -m 'not smoke'``）。
需要真实调用时：

    DEEPSEEK_API_KEY=xxx uv run pytest -m smoke
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.llm.base import ChatMessage
from app.llm.deepseek import DeepSeekProvider

pytestmark = pytest.mark.smoke


async def test_real_deepseek_chat_smoke() -> None:
    settings = get_settings()
    if not settings.llm_configured or settings.deepseek_api_key is None:
        pytest.skip("未配置 DEEPSEEK_API_KEY，跳过真实 API 冒烟测试")

    provider = DeepSeekProvider(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
        max_retries=0,
    )
    try:
        response = await provider.chat(
            [ChatMessage(role="user", content="只回复两个字：收到")], max_tokens=16
        )
        assert response.content.strip()
    finally:
        await provider.aclose()
