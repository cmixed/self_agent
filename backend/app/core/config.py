"""应用级配置。

所有配置来自环境变量或仓库根目录的 ``.env``。密钥只保存在 ``SecretStr``
中，禁止写入源码、禁止打印到日志、禁止返回给前端（见 AGENTS.md §9/§21）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> 仓库根目录
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """全局配置。字段名与 .env 中的大写下划线变量一一对应。"""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
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

    # --- Agent ---
    # 单个节点的最大重试次数（Validator 重试见 Phase 4，§16）
    max_retries: int = 2

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
        if self.llm_provider.lower() == "deepseek":
            return self.deepseek_api_key is not None and bool(
                self.deepseek_api_key.get_secret_value().strip()
            )
        return False


@lru_cache
def get_settings() -> Settings:
    """返回进程级唯一配置对象（测试中可通过 ``get_settings.cache_clear()`` 重置）。"""
    return Settings()
