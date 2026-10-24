"""自定义 LLM Provider 服务（UI 管理）。

密钥策略（用户已确认）：**环境变量优先，其次 UI 填写的本地值**。

- 若配置了 ``api_key_env`` 且该变量存在（真实环境变量或 backend/.env），使用它；
- 否则使用库中保存的 ``api_key``（明文仅存本地 SQLite，绝不回传前端）；
- 前端只能看到「来源 + 末 4 位」的提示，用于确认"配对了没有"。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4

from dotenv import dotenv_values

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.provider_store import ProviderStore
from app.llm import registry
from app.llm.factory import reset_llm
from app.llm.provider_config import ProviderConfig, mask_api_key
from app.memory.repository import ProviderRecord, ProviderRepository
from app.memory.sqlite import SqliteDatabase

logger = get_logger(__name__)

_ALLOWED_SCHEMES = ("http://", "https://")

# 线路协议：openai = OpenAI 兼容 /v1；ollama = Ollama 原生 /api/chat（可关闭思考）
_ALLOWED_FLAVORS = ("openai", "ollama")


class ProviderNotFoundError(Exception):
    """自定义 Provider 不存在。"""


class ProviderValidationError(Exception):
    """配置不合法（字段缺失/地址格式不对）。"""


@dataclass(frozen=True)
class ProviderView:
    """可安全回传前端的视图（**不含**密钥，仅来源与末 4 位提示）。"""

    provider_id: str
    label: str
    base_url: str
    model: str
    api_key_env: str
    key_source: str  # env / db / none
    key_hint: str
    requires_api_key: bool
    is_local: bool
    timeout_seconds: float
    max_retries: int
    flavor: str
    disable_thinking: bool
    created_at: str
    updated_at: str


def _env_file_values(settings: Settings) -> dict[str, str]:
    """读取 backend/.env 的键值（pydantic-settings 不会把 .env 注入 os.environ）。"""
    env_file = settings.model_config.get("env_file")
    if not env_file:
        return {}
    try:
        values = dotenv_values(str(env_file))
    except OSError:  # pragma: no cover - 文件不可读时按无值处理
        return {}
    return {key: value for key, value in values.items() if value}


def resolve_api_key(record: ProviderRecord, settings: Settings) -> tuple[str, str]:
    """返回 (密钥, 来源)。环境变量优先。"""
    if record.api_key_env:
        env_value = os.environ.get(record.api_key_env) or _env_file_values(settings).get(
            record.api_key_env
        )
        if env_value and env_value.strip():
            return env_value.strip(), "env"
    if record.api_key.strip():
        return record.api_key.strip(), "db"
    return "", "none"


def _hint(key: str) -> str:
    return mask_api_key(key)


def to_config(record: ProviderRecord, settings: Settings) -> ProviderConfig:
    api_key, _ = resolve_api_key(record, settings)
    return ProviderConfig(
        id=record.provider_id,
        label=record.label,
        base_url=record.base_url,
        model=record.model,
        api_key=api_key,
        api_key_env=record.api_key_env or "API_KEY",
        requires_api_key=record.requires_api_key,
        is_local=record.is_local,
        timeout_seconds=record.timeout_seconds,
        max_retries=record.max_retries,
        flavor=record.flavor,
        disable_thinking=record.disable_thinking,
        managed=True,
        key_source=resolve_api_key(record, settings)[1],
        key_hint=mask_api_key(api_key),
    )


def to_view(record: ProviderRecord, settings: Settings) -> ProviderView:
    api_key, source = resolve_api_key(record, settings)
    return ProviderView(
        provider_id=record.provider_id,
        label=record.label,
        base_url=record.base_url,
        model=record.model,
        api_key_env=record.api_key_env,
        key_source=source,
        key_hint=_hint(api_key),
        requires_api_key=record.requires_api_key,
        is_local=record.is_local,
        timeout_seconds=record.timeout_seconds,
        max_retries=record.max_retries,
        flavor=record.flavor,
        disable_thinking=record.disable_thinking,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class ProviderService:
    """自定义 Provider 的 CRUD，并负责同步内存注册表与失效 Provider 缓存。"""

    def __init__(self, database: SqliteDatabase) -> None:
        self._repository = ProviderRepository(database)

    async def list_providers(self) -> list[ProviderView]:
        settings = get_settings()
        return [to_view(record, settings) for record in await self._repository.list_providers()]

    async def get_provider(self, provider_id: str) -> ProviderView:
        record = await self._require(provider_id)
        return to_view(record, get_settings())

    async def create_provider(
        self,
        *,
        label: str,
        base_url: str,
        model: str,
        api_key: str = "",
        api_key_env: str = "",
        requires_api_key: bool = True,
        is_local: bool = False,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        flavor: str = "openai",
        disable_thinking: bool = False,
    ) -> ProviderView:
        label, base_url, model = self._validate(label, base_url, model)
        flavor = self._validate_flavor(flavor)
        # disable_thinking 原样保存，但**只在 flavor="ollama"（本地 Ollama 原生协议）
        # 时生效**；openai 协议下 factory 会有意忽略它（不报错、不改请求体）。
        # 界面已按协议禁用该勾选，这里不额外拒绝，避免用户在切换协议时被卡住。
        if requires_api_key and not api_key.strip() and not api_key_env.strip():
            raise ProviderValidationError(
                "需要密钥的 Provider 必须填写 API Key，或指定环境变量名（如 MOONSHOT_API_KEY）"
            )

        provider_id = f"custom-{uuid4().hex[:8]}"
        record = await self._repository.create_provider(
            provider_id=provider_id,
            label=label,
            base_url=base_url,
            model=model,
            api_key=api_key.strip(),
            api_key_env=api_key_env.strip(),
            requires_api_key=requires_api_key,
            is_local=is_local,
            timeout_seconds=max(5.0, float(timeout_seconds)),
            max_retries=max(0, int(max_retries)),
            flavor=flavor,
            disable_thinking=bool(disable_thinking),
        )
        await self.refresh_registry()
        return to_view(record, get_settings())

    async def update_provider(
        self,
        provider_id: str,
        *,
        label: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_key_env: str | None = None,
        requires_api_key: bool | None = None,
        is_local: bool | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        flavor: str | None = None,
        disable_thinking: bool | None = None,
    ) -> ProviderView:
        current = await self._require(provider_id)
        merged_label, merged_base, merged_model = self._validate(
            label if label is not None else current.label,
            base_url if base_url is not None else current.base_url,
            model if model is not None else current.model,
        )
        fields: dict[str, object] = {
            "label": merged_label,
            "base_url": merged_base,
            "model": merged_model,
        }
        # api_key：None=保持不变，空串=清空
        if api_key is not None:
            fields["api_key"] = api_key.strip()
        if api_key_env is not None:
            fields["api_key_env"] = api_key_env.strip()
        if requires_api_key is not None:
            fields["requires_api_key"] = int(requires_api_key)
        if is_local is not None:
            fields["is_local"] = int(is_local)
        if timeout_seconds is not None:
            fields["timeout_seconds"] = max(5.0, float(timeout_seconds))
        if max_retries is not None:
            fields["max_retries"] = max(0, int(max_retries))
        if flavor is not None:
            fields["flavor"] = self._validate_flavor(flavor)
        if disable_thinking is not None:
            fields["disable_thinking"] = int(bool(disable_thinking))

        record = await self._repository.update_provider(provider_id, **fields)
        if record is None:
            raise ProviderNotFoundError(f"Provider 不存在：{provider_id}")

        # 配置变了：重建进程内 Provider，避免继续用旧密钥/地址
        reset_llm()
        await self.refresh_registry()
        return to_view(record, get_settings())

    async def delete_provider(self, provider_id: str) -> None:
        await self._require(provider_id)
        if not await self._repository.delete_provider(provider_id):
            raise ProviderNotFoundError(f"Provider 不存在：{provider_id}")
        await self._deactivate_if_active(provider_id)
        reset_llm()
        await self.refresh_registry()

    async def refresh_registry(self) -> list[ProviderConfig]:
        """把库中配置装进内存注册表（启动时与每次变更后调用）。"""
        settings = get_settings()
        configs = [
            to_config(record, settings) for record in await self._repository.list_providers()
        ]
        registry.set_custom_providers(configs)
        return configs

    async def _require(self, provider_id: str) -> ProviderRecord:
        record = await self._repository.get_provider(provider_id)
        if record is None:
            raise ProviderNotFoundError(f"Provider 不存在：{provider_id}")
        return record

    @staticmethod
    def _validate(label: str, base_url: str, model: str) -> tuple[str, str, str]:
        cleaned_base = base_url.strip().rstrip("/")
        cleaned_model = model.strip()
        # 名称留空 → 用模型名兜底（避免把 custom-xxxxxxxx 这种内部 id 显示给用户）
        cleaned_label = label.strip() or cleaned_model
        if not cleaned_label:
            raise ProviderValidationError("名称不能为空")
        if not cleaned_base.startswith(_ALLOWED_SCHEMES):
            raise ProviderValidationError("接口地址必须以 http:// 或 https:// 开头")
        if not cleaned_model:
            raise ProviderValidationError("模型名不能为空")
        return cleaned_label, cleaned_base, cleaned_model

    @staticmethod
    def _validate_flavor(flavor: str) -> str:
        cleaned = (flavor or "openai").strip().lower()
        if cleaned not in _ALLOWED_FLAVORS:
            raise ProviderValidationError(
                f"不支持的接口协议：{flavor}（可选：{'/'.join(_ALLOWED_FLAVORS)}）"
            )
        return cleaned

    async def _deactivate_if_active(self, provider_id: str) -> None:
        """删掉正在使用的 Provider 时，回退到环境默认值（不允许悬空）。"""
        settings = get_settings()
        store = ProviderStore(settings.settings_path)
        if store.load() == provider_id:
            store.save("")
            reset_llm()
            logger.warning(
                "当前 Provider 已被删除，回退到环境默认值",
                extra={"event": "provider_deleted", "node": provider_id},
            )
