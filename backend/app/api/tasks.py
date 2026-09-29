"""任务接口。

Phase 2：同步执行 Agent Graph 并返回结果。
SSE 进度流（Phase 2B，§19）与任务持久化（Phase 5）后续补充。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_task_service
from app.core.logging import get_logger
from app.models.schemas import (
    PlanOut,
    PlanStepOut,
    StepResultOut,
    TaskRequest,
    TaskResponse,
)
from app.services.task_service import TaskService

router = APIRouter(prefix="/api", tags=["tasks"])
logger = get_logger(__name__)


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    request: TaskRequest,
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    state = await service.run(request.query, user_preferences=request.user_preferences)

    raw_plan = state.get("plan")
    plan = (
        PlanOut(
            goal=raw_plan["goal"],
            needs_retrieval=raw_plan["needs_retrieval"],
            steps=[PlanStepOut(**step) for step in raw_plan["steps"]],
        )
        if raw_plan
        else None
    )

    return TaskResponse(
        task_id=state.get("task_id", ""),
        status=state.get("task_status", "failed"),
        plan=plan,
        step_results=[StepResultOut(**result) for result in state.get("step_results", [])],
        final_answer=state.get("final_answer", ""),
    )
