"""FastAPI 应用入口。

启动：``uv run uvicorn app.main:app --reload``（在 backend/ 目录下执行）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import chat, documents, health, tasks
from app.api.deps import build_database
from app.api.errors import register_exception_handlers
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.llm.factory import close_llm

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    await asyncio.to_thread(build_database().initialize)
    logger.info(
        "应用启动 "
        f"env={settings.app_env} provider={settings.llm_provider} "
        f"llm_configured={settings.llm_configured}",
        extra={"event": "startup", "status": "ok"},
    )
    try:
        yield
    finally:
        await close_llm()
        logger.info("应用关闭", extra={"event": "shutdown", "status": "ok"})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="基于 RAG 的个人任务型智能体",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(tasks.router)
    app.include_router(documents.router)
    register_exception_handlers(app)
    return app


app = create_app()
