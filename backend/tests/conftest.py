"""pytest 全局配置。

单元测试不依赖真实 DeepSeek API，也不读写仓库内的运行数据：
- 禁用本机 ``.env``；
- ``SQLITE_PATH`` 指向临时目录；
- 每个测试清空进程级缓存（向量集合 / 持久化句柄）。

``smoke`` 标记的测试例外：它们就是要验证真实 API，必须使用本机 ``.env``。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.api.deps import reset_caches
from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolate_settings(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    if request.node.get_closest_marker("smoke"):
        yield
        return

    monkeypatch.setattr(
        Settings,
        "model_config",
        {**Settings.model_config, "env_file": None},
    )
    # 运行时 Provider 选择也指向临时目录，避免读写真实 data/settings.json
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("CHECKPOINT_PATH", str(tmp_path / "checkpoints.db"))
    monkeypatch.setenv("SETTINGS_PATH", str(tmp_path / "settings.json"))

    get_settings.cache_clear()
    reset_caches()
    yield
    get_settings.cache_clear()
    reset_caches()
