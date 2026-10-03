"""FastAPI 应用入口。

启动：``uv run uvicorn app.main:app --reload``（在 backend/ 目录下执行）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import chat, documents, health, memory, tasks
from app.api import settings as settings_api
from app.api.deps import (
    build_checkpoint_store,
    build_database,
    build_task_repository,
    get_checkpoint_store,
)
from app.api.errors import register_exception_handlers
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.llm.factory import close_llm, current_llm_provider

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    configure_logging()
    settings = get_settings()
    await asyncio.to_thread(build_database().initialize)
    reconciled = await build_task_repository().reconcile_running_tasks()
    if reconciled:
        logger.warning(
            f"已将 {reconciled} 条重启前遗留的「运行中」任务标记为已取消",
            extra={"event": "tasks_reconciled", "status": "ok"},
        )
    if settings.checkpoint_enabled:
        await build_checkpoint_store().start()
    logger.info(
        "应用启动 "
        f"env={settings.app_env} provider={current_llm_provider()} "
        f"llm_configured={settings.provider_configured(current_llm_provider())} "
        f"checkpoint={settings.checkpoint_enabled}",
        extra={"event": "startup", "status": "ok"},
    )
    try:
        yield
    finally:
        store = get_checkpoint_store()
        if store is not None:
            await store.close()
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
    app.include_router(settings_api.router)
    app.include_router(chat.router)
    app.include_router(tasks.router)
    app.include_router(documents.router)
    app.include_router(memory.router)
    register_exception_handlers(app)
    return app


app = create_app()
