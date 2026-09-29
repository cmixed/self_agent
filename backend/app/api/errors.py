"""统一错误处理。

把 :class:`~app.llm.base.LLMError` 映射为可读的 HTTP 状态与错误结构，
无论异常来自依赖注入还是业务节点（见 AGENTS.md §20）。
对外只暴露可安全展示的信息，绝不返回 traceback / 密钥 / 内部配置。
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.llm.base import (
    LLMConfigError,
    LLMError,
    LLMRateLimitError,
    LLMResponseFormatError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.models.schemas import ErrorResponse

logger = get_logger(__name__)

# 具体的异常类型 -> (HTTP 状态码, 可安全展示的说明)
_ERROR_STATUS: dict[type[LLMError], tuple[int, str]] = {
    LLMConfigError: (status.HTTP_503_SERVICE_UNAVAILABLE, "LLM 服务未正确配置"),
    LLMTimeoutError: (status.HTTP_504_GATEWAY_TIMEOUT, "上游模型服务超时"),
    LLMRateLimitError: (status.HTTP_429_TOO_MANY_REQUESTS, "上游模型服务限流，请稍后重试"),
    LLMUpstreamError: (status.HTTP_502_BAD_GATEWAY, "上游模型服务异常"),
    LLMResponseFormatError: (status.HTTP_502_BAD_GATEWAY, "模型返回内容格式不符合要求"),
}
_DEFAULT_STATUS = (status.HTTP_502_BAD_GATEWAY, "模型服务调用失败")


def resolve_llm_error(exc: LLMError) -> tuple[int, str]:
    """按 MRO 匹配，允许 LLMError 的自定义子类复用父类映射。

    返回 (HTTP 状态码, 可安全展示的说明)。
    """
    for exc_type in type(exc).__mro__:
        if exc_type in _ERROR_STATUS:
            return _ERROR_STATUS[exc_type]
    return _DEFAULT_STATUS


async def llm_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, LLMError)
    http_status, detail = resolve_llm_error(exc)

    logger.warning(
        "LLM 调用失败",
        extra={
            "event": "llm_failed",
            "status": "error",
            "error_type": exc.error_type,
            "node": request.url.path,
        },
    )
    body = ErrorResponse(
        error=exc.error_type,
        error_type=exc.error_type,
        detail=detail,
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LLMError, llm_error_handler)
