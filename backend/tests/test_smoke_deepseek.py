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
        # 注意：DeepSeek 是推理模型，reasoning_content 与 content **共享** max_tokens 预算。
        # 预算过小（例如 16）会在生成正式答案前就被截断（finish_reason=length），
        # 导致 content 为空而误报失败。这里给足预算，仅验证「真实 API 可调用」。
        response = await provider.chat(
            [ChatMessage(role="user", content="只回复两个字：收到")], max_tokens=256
        )
        assert response.content.strip(), (
            f"真实 API 返回空 content（model={response.model}，usage={response.usage}）"
        )
    finally:
        await provider.aclose()
