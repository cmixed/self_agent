"""任务接口。

- ``POST /api/tasks``：同步执行 Agent Graph 并返回完整结果（结果持久化到 SQLite）。
- ``POST /api/tasks/stream``：以 SSE 推送执行进度（AGENTS.md §19）。
- ``GET /api/tasks/{task_id}``：查询已保存的任务记录（AGENTS.md §18）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import (
    get_checkpoint_store,
    get_memory_service,
    get_task_repository,
    get_task_service,
    get_user_id,
)
from app.core.checkpoint import CheckpointStore
from app.core.logging import get_logger
from app.memory.repository import TaskRepository
from app.models.schemas import (
    TaskDetailResponse,
    TaskListResponse,
    TaskRequest,
    TaskResponse,
    TaskStateResponse,
    TaskSummaryOut,
)
from app.services.memory_service import MemoryService
from app.services.task_service import TaskService, task_result

router = APIRouter(prefix="/api", tags=["tasks"])
logger = get_logger(__name__)


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    request: Request,
    payload: TaskRequest,
    service: TaskService = Depends(get_task_service),
    memory_service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> TaskResponse:
    # 先生成 task_id 并写入 request.state：失败时错误响应也会带上它，
    # 便于前端通过 GET /api/tasks/{id} 查询失败记录。
    task_id = str(uuid4())
    request.state.task_id = task_id

    # 长期偏好 + 本次请求覆盖（请求优先）
    stored = await memory_service.get_preferences(user_id)
    preferences = {**stored, **(payload.user_preferences or {})}

    state = await service.run(
        payload.query,
        user_preferences=preferences,
        task_id=task_id,
        user_id=user_id,
    )
    result = task_result(state, max_retries=service.max_retries)
    await memory_service.extract_from_task(
        user_id, query=payload.query, result=result, task_id=task_id
    )
    return TaskResponse.model_validate(result)


def _to_summary(record: Any) -> TaskSummaryOut:
    result = record.result or {}
    return TaskSummaryOut(
        task_id=record.task_id,
        query=record.query,
        status=record.status,
        created_at=record.created_at,
        finished_at=record.finished_at,
        error_type=record.error_type,
        retry_count=int(result.get("retry_count") or 0),
        failed_chapters=list(result.get("failed_chapters") or []),
    )


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    repository: TaskRepository = Depends(get_task_repository),
    user_id: str = Depends(get_user_id),
) -> TaskListResponse:
    """按用户列出任务记录（最新在前），供前端任务历史页使用。"""
    records = await repository.list_tasks(user_id=user_id, limit=limit)
    return TaskListResponse(tasks=[_to_summary(record) for record in records])


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    task_id: str,
    repository: TaskRepository = Depends(get_task_repository),
) -> TaskDetailResponse:
    record = await repository.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    payload = dict(record.result or {})
    payload.update(
        {
            "task_id": record.task_id,
            "status": record.status,
            "user_id": record.user_id,
            "query": record.query,
            "created_at": record.created_at,
            "finished_at": record.finished_at,
            "error_type": record.error_type,
        }
    )
    return TaskDetailResponse.model_validate(payload)


@router.get("/tasks/{task_id}/state", response_model=TaskStateResponse)
async def get_task_state(
    task_id: str,
    store: CheckpointStore | None = Depends(get_checkpoint_store),
) -> TaskStateResponse:
    """读取该任务最近的 Agent checkpoint 状态摘要（AGENTS.md §17 的结构化状态）。

    只返回结构化进度，不返回模型消息或隐藏推理过程。
    """
    saver = store.saver if store is not None else None
    if saver is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Checkpoint 未启用"
        )

    checkpoint_tuple = await saver.aget_tuple({"configurable": {"thread_id": task_id}})
    if checkpoint_tuple is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="没有找到该任务的 checkpoint"
        )

    checkpoint = checkpoint_tuple.checkpoint or {}
    values = checkpoint.get("channel_values") or {}
    return TaskStateResponse(
        task_id=task_id,
        checkpoint_id=checkpoint.get("id"),
        status=values.get("task_status"),
        current_step=values.get("current_step"),
        is_complete=bool(values.get("is_complete")),
        retry_count=int(values.get("retry_count") or 0),
        outline=[str(section.get("title", "")) for section in values.get("outline") or []],
        chapters_written=len([s for s in values.get("sections") or [] if s.get("content")]),
        sources_count=len(values.get("retrieved_documents") or []),
    )


@router.post("/tasks/stream")
async def stream_task(
    request: Request,
    payload: TaskRequest,
    service: TaskService = Depends(get_task_service),
    memory_service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    """以 SSE 推送 Agent 执行进度。

    前端不应展示模型隐藏推理过程。
    """
    task_id = str(uuid4())
    request.state.task_id = task_id

    stored = await memory_service.get_preferences(user_id)
    preferences = {**stored, **(payload.user_preferences or {})}
    completed: dict = {}

    async def event_source() -> AsyncIterator[str]:
        async for event in service.stream(
            payload.query,
            user_preferences=preferences,
            task_id=task_id,
            user_id=user_id,
        ):
            if event.get("event") == "task_completed" and event.get("result"):
                completed.update(event["result"])
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # 任务完成后提取长期记忆（best-effort，失败不影响已推送的结果）
        if completed:
            await memory_service.extract_from_task(
                user_id, query=payload.query, result=completed, task_id=task_id
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
