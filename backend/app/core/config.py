"""应用级配置。

所有配置来自环境变量或 ``backend/.env``。密钥只保存在 ``SecretStr``
中，禁止写入源码、禁止打印到日志、禁止返回给前端（见 AGENTS.md §9/§21）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.limits import (
    DEFAULT_MAX_SECTIONS,
    DEFAULT_TARGET_SECTIONS,
    DEFAULT_TOTAL_CHARS,
    HARD_SECTION_CEILING,
    MAX_TOTAL_CHARS,
    MIN_SECTIONS,
    MIN_TOTAL_CHARS,
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
    # 复用同一把 GLM_API_KEY 的额外模型（逗号分隔，如 glm-5.3-flashx）。
    # 每个模型会成为切换器里的独立条目（id = ``glm:<model>``），无需重复填密钥。
    glm_extra_models: str = ""
    glm_timeout_seconds: float = 60.0
    glm_max_retries: int = 2

    # --- 自定义 OpenAI 兼容端点（.env 版本；UI 管理的条目存 SQLite，见 P3）---
    custom_base_url: str = ""
    custom_api_key: SecretStr | None = None
    custom_model: str = ""
    custom_label: str = "自定义接口"
    custom_api_key_env: str = "CUSTOM_API_KEY"
    custom_requires_api_key: bool = True
    custom_is_local: bool = False
    custom_timeout_seconds: float = 120.0
    custom_max_retries: int = 2
    # 线路协议：openai = /v1 兼容；ollama = 原生 /api/chat（可关闭思考）
    custom_flavor: str = "openai"
    # 关闭思考：**只对本地 Ollama 有意义**。只有当 CUSTOM_FLAVOR=ollama
    # （即该自定义端点其实是本地 Ollama 原生协议）时才会生效；
    # CUSTOM_FLAVOR=openai 时本项被忽略（factory 有意不透传）。
    custom_disable_thinking: bool = False

    # --- Ollama（本地模型，OpenAI 兼容端点）---
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = ""
    # 本地推理慢，默认超时与重试都更宽松
    ollama_timeout_seconds: float = 300.0
    ollama_max_retries: int = 1

    # --- 运行时设置（前端切换 LLM Provider 的持久化，§18 /api/settings）---
    settings_path: Path = _REPO_ROOT / "data" / "settings.json"

    # --- 邮件发送（把生成结果发送到邮箱）---
    # SMTP 密码只来自环境变量 / backend/.env，禁止返回前端或写入日志。
    smtp_host: str = ""
    smtp_port: int = 465
    # ssl（465，常见于 QQ / 163）/ starttls（587，常见于 Gmail）/ none（仅本地中继）
    smtp_security: Literal["ssl", "starttls", "none"] = "ssl"
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_from: str = ""
    smtp_from_name: str = "个人知识库 Agent"
    smtp_timeout_seconds: float = 15.0
    # 同一用户 + 同一任务 + 同一收件人的发送冷却（秒）；0 = 不限制
    email_cooldown_seconds: float = 30.0

    # --- Agent ---
    # 单个节点的最大重试次数（Validator 重试见 Phase 4，§16）
    max_retries: int = 2
    # 长文分章节预算（§15）：target 是提示词里的**参考上限**（章节数由大纲按
    # 任务需要动态决定，可以是 1 章 = 不拆分），max 为实际生成上限。
    # 两者都会被夹到 [MIN_SECTIONS, HARD_SECTION_CEILING]，且 target ≤ max。
    target_sections: int = DEFAULT_TARGET_SECTIONS
    max_sections: int = DEFAULT_MAX_SECTIONS
    # 目标总字数（软目标）：按章节数分摊后写进写作/校验提示词。
    # 注意这不是 max_tokens 硬上限——硬截断只会得到半截章节。
    target_total_chars: int = DEFAULT_TOTAL_CHARS
    # 默认执行深度：auto（确定性路由）/ brief / longform
    default_depth: str = "auto"
    # 任务完成后是否自动提取长期记忆：
    # - longform 总是提取；
    # - brief / direct 仅在 query 命中明确长期信号（记住 / 以后都 / 我的研究方向…）
    #   时提取，避免每个短问答都多一次模型调用；
    # - 原文输出（verbatim）从不提取。
    memory_auto_extract: bool = True
    # 单次提取的墙钟上限（best-effort）：超时只记日志，不影响任务结果。
    memory_extract_timeout_seconds: float = 20.0
    # 启动时是否自动写入 3 个内置技能；默认关闭（用户显式启用/创建即可）
    seed_builtin_skills: bool = False

    # --- 技能（§ 技能生成）---
    # 从文档生成技能时单次送入模型的最大字符数；长文档按此切块提炼
    # （最多 MAX_SKILL_GENERATION_CHUNKS 段，超出部分如实提示）
    skill_generate_max_chars: int = 12000
    # 技能目录：文件是唯一内容源（<skills_dir>/<skill_id>/SKILL.md + 附件）
    skills_dir: Path = _REPO_ROOT / "data" / "skills"

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

    @property
    def glm_extra_model_list(self) -> list[str]:
        """GLM 额外模型列表（去空、去重，保持配置顺序）。"""
        models: list[str] = []
        for item in self.glm_extra_models.split(","):
            model = item.strip()
            if model and model not in models:
                models.append(model)
        return models

    def provider_configured(self, provider: str) -> bool:
        """按 Provider 名称检查配置是否就绪（不校验可用性；占位符视为未配置）。"""
        name = provider.strip().lower()
        key: SecretStr | None
        if name == "deepseek":
            key = self.deepseek_api_key
        elif name == "glm" or name.startswith("glm:"):
            # glm:<model> 是同一把 GLM_API_KEY 下的额外模型
            key = self.glm_api_key
        elif name == "custom":
            if not self.custom_base_url.strip() or not self.custom_model.strip():
                return False
            if not self.custom_requires_api_key:
                return True
            key = self.custom_api_key
        elif name == "ollama":
            # 本地服务无需密钥，配置了模型名即视为就绪
            return bool(self.ollama_base_url.strip() and self.ollama_model.strip())
        else:
            return False
        if key is None:
            return False
        value = key.get_secret_value().strip()
        return bool(value) and not _is_placeholder(value)

    @property
    def effective_smtp_from(self) -> str:
        """发件人地址：未显式配置时回退到登录账号。"""
        return (self.smtp_from or self.smtp_username).strip()

    @property
    def smtp_configured(self) -> bool:
        """SMTP 是否具备发信条件（不校验服务器可用性）。"""
        if not self.smtp_host.strip() or not self.effective_smtp_from:
            return False
        if not self.smtp_username.strip():
            # 本地中继可能不需要认证；仍要求显式配置发件人
            return True
        password = self.smtp_password.get_secret_value().strip() if self.smtp_password else ""
        return bool(password) and not _is_placeholder(password)

    @property
    def effective_max_sections(self) -> int:
        """实际生成上限：夹到 [MIN_SECTIONS, HARD_SECTION_CEILING]。"""
        return max(MIN_SECTIONS, min(self.max_sections, HARD_SECTION_CEILING))

    @property
    def effective_total_chars(self) -> int:
        """目标总字数：夹到 [MIN_TOTAL_CHARS, MAX_TOTAL_CHARS]。"""
        return max(MIN_TOTAL_CHARS, min(self.target_total_chars, MAX_TOTAL_CHARS))

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
        if name.startswith("glm:"):
            return name.partition(":")[2] or self.glm_model
        if name == "custom":
            return self.custom_model
        if name == "ollama":
            return self.ollama_model
        return ""


@lru_cache
def get_settings() -> Settings:
    """返回进程级唯一配置对象（测试中可通过 ``get_settings.cache_clear()`` 重置）。"""
    return Settings()
