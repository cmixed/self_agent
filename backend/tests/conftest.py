"""pytest 全局配置。

单元测试不依赖真实 DeepSeek API；真实调用集中在 ``test_smoke_deepseek.py``，
默认被 ``-m 'not smoke'`` 排除。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolate_settings(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """让测试不读取本机 ``.env``，避免本地配置影响结果。

    ``smoke`` 标记的测试例外：它们就是要验证真实 API，必须使用本机 ``.env``。
    """
    if request.node.get_closest_marker("smoke"):
        yield
        return

    monkeypatch.setattr(
        Settings,
        "model_config",
        {**Settings.model_config, "env_file": None},
    )
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
