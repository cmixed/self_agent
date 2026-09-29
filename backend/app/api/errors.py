"""把领域异常转换为 HTTP 响应。

映射规则集中在 ``app/core/errors.py``，本模块只负责注册 FastAPI handler。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import HANDLED_BASES, error_type_of, resolve_error
from app.core.logging import get_logger
from app.models.schemas import ErrorResponse

logger = get_logger(__name__)


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    http_status, detail = resolve_error(exc)
    error_type = error_type_of(exc)

    logger.warning(
        "请求处理失败",
        extra={
            "event": "request_failed",
            "status": "error",
            "error_type": error_type,
            "node": request.url.path,
        },
    )
    body = ErrorResponse(error=error_type, error_type=error_type, detail=detail)
    return JSONResponse(status_code=http_status, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    for exc_type in HANDLED_BASES:
        app.add_exception_handler(exc_type, app_error_handler)
