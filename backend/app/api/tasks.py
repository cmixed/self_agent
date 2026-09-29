"""任务接口。

- ``POST /api/tasks``：同步执行 Agent Graph 并返回完整结果。
- ``POST /api/tasks/stream``：以 SSE 推送执行进度（AGENTS.md §19）。

任务持久化与 ``GET /api/tasks/{id}`` 属于 Phase 5。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_task_service
from app.core.logging import get_logger
from app.models.schemas import TaskRequest, TaskResponse
from app.services.task_service import TaskService, task_result

router = APIRouter(prefix="/api", tags=["tasks"])
logger = get_logger(__name__)


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    request: TaskRequest,
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    state = await service.run(request.query, user_preferences=request.user_preferences)
    return TaskResponse.model_validate(task_result(state))


@router.post("/tasks/stream")
async def stream_task(
    request: TaskRequest,
    service: TaskService = Depends(get_task_service),
) -> StreamingResponse:
    """以 SSE 推送 Agent 执行进度。

    当前无任务持久化，进度流由本次请求驱动；Phase 5 接入 SQLite 后再补充
    ``GET /api/tasks/{id}/stream``。前端不应展示模型隐藏推理过程。
    """

    async def event_source() -> AsyncIterator[str]:
        async for event in service.stream(request.query, user_preferences=request.user_preferences):
            payload = json.dumps(event, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
