"""Provider 配置结构（工厂与自定义 Provider 注册表共用）。

单独成文件的理由：``registry`` 需要构造它，而 ``factory`` 需要读取注册表；
放在 factory 里会形成循环导入。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    """一个可用的 LLM 端点配置（内置与自定义共用同一结构）。"""

    id: str
    label: str
    base_url: str
    model: str
    api_key: str = ""
    api_key_env: str = "API_KEY"
    requires_api_key: bool = True
    is_local: bool = False
    timeout_seconds: float = 60.0
    max_retries: int = 2
    # --- 展示用元数据（不含密钥本身）---
    managed: bool = False  # True = 用户自定义（可在 UI 编辑/删除）
    key_source: str = "env"  # env / db / none
    key_hint: str = ""  # 例如 ****abcd

    @property
    def available(self) -> bool:
        """是否具备调用条件（密钥就绪 / 本地服务无需密钥）。"""
        if not self.requires_api_key:
            return bool(self.base_url.strip() and self.model.strip())
        value = (self.api_key or "").strip()
        return bool(self.base_url.strip() and self.model.strip() and value)


def mask_api_key(api_key: str) -> str:
    """密钥提示：只露末 4 位，绝不回传完整密钥（AGENTS.md §9/§21）。"""
    if not api_key:
        return ""
    return f"****{api_key[-4:]}" if len(api_key) > 4 else "已设置"
