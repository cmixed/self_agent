"""FastAPI 应用入口。

启动：``uv run uvicorn app.main:app --reload``（在 backend/ 目录下执行）。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import (
    categories,
    chat,
    documents,
    health,
    memory,
    presets,
    providers,
    providers_crud,
    skills,
    tasks,
)
from app.api import settings as settings_api
from app.api.deps import (
    build_checkpoint_store,
    build_chroma_store,
    build_database,
    build_preset_service,
    build_provider_service,
    build_skill_service,
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
    # 装载 UI 管理的自定义 Provider 到内存注册表（工厂同步读取，见 llm/registry.py）
    try:
        await build_provider_service().refresh_registry()
    except Exception as exc:  # pragma: no cover - 配置异常不应阻塞启动
        logger.warning(f"自定义 Provider 装载失败：{exc}", extra={"event": "providers_load_failed"})
    reconciled = await build_task_repository().reconcile_running_tasks()
    if reconciled:
        logger.warning(
            f"已将 {reconciled} 条重启前遗留的「运行中」任务标记为已取消",
            extra={"event": "tasks_reconciled", "status": "ok"},
        )
    # 预热向量库连接：Chroma 首次打开约 0.3-0.5s，放到启动阶段，
    # 避免工作台/知识库的首个请求卡顿（失败不阻塞启动，首次请求再报错）
    with contextlib.suppress(Exception):
        await asyncio.to_thread(build_chroma_store)

    # 内置技能 seed（幂等：已存在的不覆盖，用户修改保留）。
    # 默认关闭：清空测试数据后重启不应「复活」内置技能；需要时显式开启。
    if settings.seed_builtin_skills:
        await build_skill_service().ensure_seeded()
    await build_preset_service().ensure_seeded()
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
    app.include_router(skills.router)
    app.include_router(presets.router)
    app.include_router(categories.router)
    app.include_router(providers.router)
    app.include_router(providers_crud.router)
    app.include_router(chat.router)
    app.include_router(tasks.router)
    app.include_router(documents.router)
    app.include_router(memory.router)
    register_exception_handlers(app)
    return app


app = create_app()
