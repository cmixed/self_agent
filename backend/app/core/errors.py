"""领域异常 → 可读错误状态的统一映射。

放在 core 层，供服务层与 API 层共用，避免 services 反向依赖 api（见 AGENTS.md §28）。
对外只暴露可安全展示的信息，不含 traceback / 密钥 / 内部配置。
"""

from __future__ import annotations

from fastapi import status

from app.embedding.base import EmbeddingConfigError, EmbeddingError
from app.llm.base import (
    LLMConfigError,
    LLMError,
    LLMRateLimitError,
    LLMResponseFormatError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.rag.loader import DocumentError, DocumentLoadError, UnsupportedDocumentError

# 具体异常类型 -> (HTTP 状态码, 可安全展示的说明)
_ERROR_STATUS: dict[type[Exception], tuple[int, str]] = {
    # LLM
    LLMConfigError: (status.HTTP_503_SERVICE_UNAVAILABLE, "LLM 服务未正确配置"),
    LLMTimeoutError: (status.HTTP_504_GATEWAY_TIMEOUT, "上游模型服务超时"),
    LLMRateLimitError: (status.HTTP_429_TOO_MANY_REQUESTS, "上游模型服务限流，请稍后重试"),
    LLMUpstreamError: (status.HTTP_502_BAD_GATEWAY, "上游模型服务异常"),
    LLMResponseFormatError: (status.HTTP_502_BAD_GATEWAY, "模型返回内容格式不符合要求"),
    # Embedding
    EmbeddingConfigError: (status.HTTP_503_SERVICE_UNAVAILABLE, "Embedding 服务未正确配置"),
    EmbeddingError: (status.HTTP_500_INTERNAL_SERVER_ERROR, "向量化失败"),
    # 文档
    UnsupportedDocumentError: (status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "不支持的文档格式"),
    DocumentLoadError: (status.HTTP_400_BAD_REQUEST, "文档解析失败"),
    DocumentError: (status.HTTP_400_BAD_REQUEST, "文档处理失败"),
}

_DEFAULT_STATUS = (status.HTTP_502_BAD_GATEWAY, "服务调用失败")

# 需要注册 handler 的异常基类（子类经 MRO 匹配，无需逐个注册）
HANDLED_BASES: tuple[type[Exception], ...] = (LLMError, EmbeddingError, DocumentError)


def resolve_error(exc: Exception) -> tuple[int, str]:
    """按 MRO 匹配，允许自定义子类复用父类映射。

    返回 (HTTP 状态码, 可安全展示的说明)。
    """
    for exc_type in type(exc).__mro__:
        if exc_type in _ERROR_STATUS:
            return _ERROR_STATUS[exc_type]
    return _DEFAULT_STATUS


def error_type_of(exc: Exception) -> str:
    return str(getattr(exc, "error_type", "internal_error"))
