"""运行时 Provider 选择的持久化存储。

前端可通过 ``PUT /api/settings/llm-provider`` 在运行时切换 LLM Provider；
选择写入 ``data/settings.json``（见 AGENTS.md §13：与业务数据、Agent
checkpoint 分离），后端重启后仍生效。``backend/.env`` 的 ``LLM_PROVIDER``
仅作为首次启动的默认值。

文件只存 Provider 名称（``{"llm_provider": "glm"}``），绝不存密钥。
"""

from __future__ import annotations

import json
from pathlib import Path

_PROVIDERS_KEY = "llm_provider"


class ProviderStore:
    """JSON 文件形式的 Provider 选择存储。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> str | None:
        """读取已保存的 Provider 名称；文件缺失/损坏/内容非法时返回 None。"""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        value = data.get(_PROVIDERS_KEY)
        return value.strip().lower() if isinstance(value, str) and value.strip() else None

    def save(self, provider: str) -> None:
        """原子写入 Provider 选择；目录不存在时自动创建。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps({_PROVIDERS_KEY: provider}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self._path)
