"""任务接口。

- ``POST /api/tasks``：同步执行 Agent Graph 并返回完整结果（结果持久化到 SQLite）。
- ``POST /api/tasks/stream``：以 SSE 推送执行进度（AGENTS.md §19）。
- ``GET /api/tasks/{task_id}``：查询已保存的任务记录（AGENTS.md §18）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_task_repository, get_task_service, get_user_id
from app.core.logging import get_logger
from app.memory.repository import TaskRepository
from app.models.schemas import TaskDetailResponse, TaskRequest, TaskResponse
from app.services.task_service import TaskService, task_result

router = APIRouter(prefix="/api", tags=["tasks"])
logger = get_logger(__name__)


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    request: Request,
    payload: TaskRequest,
    service: TaskService = Depends(get_task_service),
    user_id: str = Depends(get_user_id),
) -> TaskResponse:
    # 先生成 task_id 并写入 request.state：失败时错误响应也会带上它，
    # 便于前端通过 GET /api/tasks/{id} 查询失败记录。
    task_id = str(uuid4())
    request.state.task_id = task_id

    state = await service.run(
        payload.query,
        user_preferences=payload.user_preferences,
        task_id=task_id,
        user_id=user_id,
    )
    return TaskResponse.model_validate(task_result(state, max_retries=service.max_retries))


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


@router.post("/tasks/stream")
async def stream_task(
    request: Request,
    payload: TaskRequest,
    service: TaskService = Depends(get_task_service),
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    """以 SSE 推送 Agent 执行进度。

    前端不应展示模型隐藏推理过程。
    """
    task_id = str(uuid4())
    request.state.task_id = task_id

    async def event_source() -> AsyncIterator[str]:
        async for event in service.stream(
            payload.query,
            user_preferences=payload.user_preferences,
            task_id=task_id,
            user_id=user_id,
        ):
            payload_json = json.dumps(event, ensure_ascii=False)
            yield f"data: {payload_json}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
