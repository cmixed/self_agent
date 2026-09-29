"""pytest 全局配置。

单元测试不依赖真实 DeepSeek API；真实调用集中在 ``test_smoke_deepseek.py``，
默认被 ``-m 'not smoke'`` 排除。
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch):
    """固定 LLM 相关环境变量，避免本机 .env 影响测试结果。"""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
