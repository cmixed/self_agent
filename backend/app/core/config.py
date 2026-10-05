"""应用级配置。

所有配置来自环境变量或 ``backend/.env``。密钥只保存在 ``SecretStr``
中，禁止写入源码、禁止打印到日志、禁止返回给前端（见 AGENTS.md §9/§21）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.limits import (
    DEFAULT_MAX_SECTIONS,
    DEFAULT_TARGET_SECTIONS,
    HARD_SECTION_CEILING,
    MIN_SECTIONS,
)

# backend/app/core/config.py -> backend/ 与仓库根目录
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]


# .env.example 中的占位值：出现这些值视为「尚未配置」，避免把模板当成真实密钥
# （真实故障：占位符非空 → 健康检查误报已配置 → 调用时才 401）
_PLACEHOLDER_KEYS = frozenset({"your_api_key_here", "your_api_key", "changeme", "sk-xxx"})


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDER_KEYS


class Settings(BaseSettings):
    """全局配置。字段名与 backend/.env 中的大写下划线变量一一对应。"""

    model_config = SettingsConfigDict(
        # 只读 backend/.env：环境文件跟随消费者所在目录；仓库根的 .env 留给
        # 外部工具（如 DeepSeek harness），结构性避免互相覆盖。
        # 真实环境变量的优先级仍高于该文件。
        env_file=_BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- 应用 ---
    app_env: str = "development"
    log_level: str = "INFO"
    # 逗号分隔的前端来源，用于 CORS
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # 无复杂用户系统（§31）：默认用户，可通过 X-User-Id 头覆盖
    default_user_id: str = "local-user"

    # --- 持久化 ---
    sqlite_path: Path = _REPO_ROOT / "data" / "sqlite" / "app.db"
    # LangGraph Checkpoint（短期记忆），与业务数据分开存放
    checkpoint_enabled: bool = True
    checkpoint_path: Path = _REPO_ROOT / "data" / "sqlite" / "checkpoints.db"

    # --- LLM Provider ---
    llm_provider: str = "deepseek"

    # --- DeepSeek (V4.1 Flash) ---
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_timeout_seconds: float = 60.0
    deepseek_max_retries: int = 2

    # --- GLM（智谱，OpenAI 兼容接口）---
    glm_api_key: SecretStr | None = None
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-5.3-flash"
    glm_timeout_seconds: float = 60.0
    glm_max_retries: int = 2

    # --- 运行时设置（前端切换 LLM Provider 的持久化，§18 /api/settings）---
    settings_path: Path = _REPO_ROOT / "data" / "settings.json"

    # --- Agent ---
    # 单个节点的最大重试次数（Validator 重试见 Phase 4，§16）
    max_retries: int = 2
    # 长文分章节预算（§15）：target 为提示词里的目标篇幅，max 为实际生成上限。
    # 两者都会被夹到 [MIN_SECTIONS, HARD_SECTION_CEILING]，且 target ≤ max。
    target_sections: int = DEFAULT_TARGET_SECTIONS
    max_sections: int = DEFAULT_MAX_SECTIONS

    # --- Embedding（独立于 LLM Provider，§12）---
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32
    # bge 中文模型建议仅对查询加指令前缀（文档侧不加）
    embedding_query_instruction: str = "为这个句子生成表示以用于检索相关文章："

    # --- RAG ---
    chunk_size: int = 800
    chunk_overlap: int = 150
    retrieval_top_k: int = 5
    chroma_dir: Path = _REPO_ROOT / "data" / "chroma"
    chroma_collection: str = "personal_kb"
    documents_dir: Path = _REPO_ROOT / "data" / "documents"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_configured(self) -> bool:
        """是否具备调用当前 LLM Provider 的必要配置（不校验可用性）。"""
        return self.provider_configured(self.llm_provider)

    def provider_configured(self, provider: str) -> bool:
        """按 Provider 名称检查密钥是否就绪（不校验可用性；占位符视为未配置）。"""
        name = provider.strip().lower()
        key: SecretStr | None
        if name == "deepseek":
            key = self.deepseek_api_key
        elif name == "glm":
            key = self.glm_api_key
        else:
            return False
        if key is None:
            return False
        value = key.get_secret_value().strip()
        return bool(value) and not _is_placeholder(value)

    @property
    def effective_max_sections(self) -> int:
        """实际生成上限：夹到 [MIN_SECTIONS, HARD_SECTION_CEILING]。"""
        return max(MIN_SECTIONS, min(self.max_sections, HARD_SECTION_CEILING))

    @property
    def effective_target_sections(self) -> int:
        """提示词目标篇幅：同样受下限约束，且不超过生成上限。"""
        return max(MIN_SECTIONS, min(self.target_sections, self.effective_max_sections))

    def provider_model(self, provider: str) -> str:
        """返回 Provider 将使用的模型名（供设置快照展示）。"""
        name = provider.strip().lower()
        if name == "deepseek":
            return self.deepseek_model
        if name == "glm":
            return self.glm_model
        return ""


@lru_cache
def get_settings() -> Settings:
    """返回进程级唯一配置对象（测试中可通过 ``get_settings.cache_clear()`` 重置）。"""
    return Settings()
