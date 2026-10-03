"""真实 GLM（智谱）API 冒烟测试。

默认被排除（pyproject 中 ``addopts = -m 'not smoke'``）。
需要真实调用时：

    GLM_API_KEY=xxx uv run pytest tests/test_smoke_glm.py -m smoke
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.llm.base import ChatMessage
from app.llm.glm import GLMProvider

pytestmark = pytest.mark.smoke


async def test_real_glm_chat_smoke() -> None:
    settings = get_settings()
    if not settings.provider_configured("glm") or settings.glm_api_key is None:
        pytest.skip("未配置 GLM_API_KEY，跳过真实 API 冒烟测试")

    provider = GLMProvider(
        api_key=settings.glm_api_key.get_secret_value(),
        base_url=settings.glm_base_url,
        model=settings.glm_model,
        timeout_seconds=settings.glm_timeout_seconds,
        max_retries=0,
    )
    try:
        response = await provider.chat(
            [ChatMessage(role="user", content="只回复两个字：收到")], max_tokens=256
        )
        assert response.content.strip(), (
            f"真实 API 返回空 content（model={response.model}，usage={response.usage}）"
        )
    finally:
        await provider.aclose()
