"""对外接口（v1）：用 API Key 提交任务、查询进度、取回结果。

定位：让「别的系统」能把任务丢进来并取走 Markdown，不必接前端。
与站内任务共用同一套编排、持久化与权限收敛——接口不是旁路。

鉴权：``X-API-Key: kb-xxxx``（在「成员」页签发）。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import (
    build_task_repository,
    get_api_key_user,
    get_category_service,
    get_document_service,
    get_memory_service,
    get_task_service,
)
from app.api.tasks import _resolve_retrieval
from app.core.logging import get_logger
from app.memory.repository import TaskRepository
from app.memory.selection import select_memories
from app.memory.users import UserRecord
from app.models.public_schemas import PublicTaskCreated, PublicTaskRequest, PublicTaskStatus
from app.models.schemas import TaskScope
from app.models.state import RetrievalMode
from app.services.category_service import CategoryService
from app.services.document_service import DocumentService
from app.services.memory_service import MemoryService
from app.services.task_service import TaskService

router = APIRouter(prefix="/api/v1", tags=["public"])
logger = get_logger(__name__)

# 后台任务需要强引用，否则可能被 GC 回收（asyncio 官方文档明确要求）
_PENDING: set[asyncio.Task[None]] = set()


async def _drain(events: AsyncIterator[dict[str, Any]]) -> None:
    """把任务事件流跑完即可：进度与结果由 TaskService 自己落库。"""
    async for _event in events:
        pass


def _spawn(coro, *, task_id: str, repository: TaskRepository) -> None:
    async def guarded() -> None:
        try:
            await coro
        except asyncio.CancelledError:  # pragma: no cover - 服务关闭时
            raise
        except Exception as exc:  # noqa: BLE001 - 对外接口必须把失败落库而不是静默
            logger.warning(
                "对外接口任务失败",
                extra={"event": "public_task_failed", "status": "error", "task_id": task_id},
            )
            with contextlib.suppress(Exception):
                await repository.fail_run(task_id=task_id, error_type=type(exc).__name__)

    task = asyncio.create_task(guarded())
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


@router.post("/tasks", response_model=PublicTaskCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_public_task(
    payload: PublicTaskRequest,
    user: UserRecord = Depends(get_api_key_user),
    service: TaskService = Depends(get_task_service),
    categories: CategoryService = Depends(get_category_service),
    documents: DocumentService = Depends(get_document_service),
    memory_service: MemoryService = Depends(get_memory_service),
    repository: TaskRepository = Depends(build_task_repository),
) -> PublicTaskCreated:
    """提交任务，立即返回 task_id；随后用 GET 轮询状态与结果。"""
    scope = (
        TaskScope(
            category_ids=list(payload.scope.get("category_ids") or []),
            document_ids=list(payload.scope.get("document_ids") or []),
        )
        if payload.scope
        else None
    )
    visible_ids = await documents.visible_document_ids(user_id=user.user_id, is_admin=user.is_admin)
    retrieval_mode, retrieval_scope = await _resolve_retrieval(
        scope,
        categories,
        cast(RetrievalMode | None, payload.retrieval_mode),
        visible_ids=visible_ids,
    )

    stored, memory_records = await memory_service.get_profile(user.user_id)
    user_memories = select_memories(memory_records, query=payload.query)

    task_id = str(uuid4())
    _spawn(
        _drain(
            service.stream(
                payload.query,
                user_preferences=stored,
                user_memories=user_memories,
                task_id=task_id,
                user_id=user.user_id,
                retrieval_scope=retrieval_scope,
                retrieval_mode=retrieval_mode,
                depth=payload.depth,
            )
        ),
        task_id=task_id,
        repository=repository,
    )
    return PublicTaskCreated(task_id=task_id, status="running")


async def _query_task(task_id: str, user: UserRecord) -> Any:
    record = await build_task_repository().get_task(task_id)
    # 别人的任务一律 404（不暴露存在性）
    if record is None or record.user_id != user.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return record


@router.get("/tasks/{task_id}", response_model=PublicTaskStatus)
async def get_public_task(
    task_id: str,
    user: UserRecord = Depends(get_api_key_user),
) -> PublicTaskStatus:
    record = await _query_task(task_id, user)
    result = record.result or {}
    return PublicTaskStatus(
        task_id=record.task_id,
        status=record.status,
        error_type=record.error_type,
        created_at=record.created_at,
        finished_at=record.finished_at,
        has_result=bool(result.get("final_answer")),
    )


@router.get("/tasks/{task_id}/result", response_model=None)
async def get_public_task_result(
    task_id: str,
    user: UserRecord = Depends(get_api_key_user),
) -> Response:
    """取回 Markdown 正文；未完成 409，失败 422。"""
    record = await _query_task(task_id, user)
    if record.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务仍在执行")
    result = record.result or {}
    markdown = str(result.get("final_answer") or "")
    if not markdown.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"任务没有产出正文（状态：{record.status}）",
        )
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{task_id}.md"',
            "X-Task-Status": record.status,
        },
    )
