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
    get_category_service,
    get_checkpoint_store,
    get_memory_service,
    get_task_registry,
    get_task_repository,
    get_task_service,
    get_user_id,
)
from app.core.checkpoint import CheckpointStore
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.task_registry import TaskRegistry
from app.memory.repository import TaskRepository
from app.models.schemas import (
    CancelTaskResponse,
    TaskDetailResponse,
    TaskListResponse,
    TaskRequest,
    TaskResponse,
    TaskScope,
    TaskStateResponse,
    TaskSummaryOut,
)
from app.services.category_service import CategoryService
from app.services.memory_service import MemoryService
from app.services.task_service import TaskService, task_result

router = APIRouter(prefix="/api", tags=["tasks"])


async def _resolve_retrieval_scope(
    scope: TaskScope | None, categories: CategoryService
) -> dict[str, object] | None:
    """把用户选择（类别 ∪ 单文档）解析为**冻结的** document_id 列表。

    返回 ``{"document_ids": [...], "label": "..."}``；未选择任何范围时返回 None
    （表示整个知识库）。选择了解析后为空时返回空 document_ids，
    由调用方拦截（不允许静默退化成"检索全部"）。
    """
    if scope is None:
        return None
    category_ids = list(dict.fromkeys(scope.category_ids))
    document_ids = list(dict.fromkeys(scope.document_ids))
    if not category_ids and not document_ids:
        return None

    resolved = await categories.resolve_scope(category_ids=category_ids, document_ids=document_ids)
    labels: list[str] = []
    if category_ids:
        known = {item.category_id: item.name for item in await categories.list_categories()}
        labels.extend(known[item] for item in category_ids if item in known)
        labels.append(f"{len(category_ids)} 个类别")
    if document_ids:
        labels.append(f"{len(document_ids)} 个文档")
    return {
        "document_ids": resolved,
        "category_ids": category_ids,
        "selected_document_ids": document_ids,
        "label": " + ".join(labels),
    }


logger = get_logger(__name__)


async def _maybe_extract_memories(
    memory_service: MemoryService,
    user_id: str,
    *,
    query: str,
    result: dict[str, Any],
    task_id: str,
) -> None:
    """只在长文任务后提取长期记忆（best-effort）。

    轻量任务（direct/brief）往往是一次性指令，提取偏好既无价值、又会多一次
    LLM 调用；长文任务才更可能暴露稳定的写作风格/格式偏好。
    """
    if not get_settings().memory_auto_extract:
        return
    if result.get("mode") != "longform":
        return
    await memory_service.extract_from_task(user_id, query=query, result=result, task_id=task_id)


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    request: Request,
    payload: TaskRequest,
    service: TaskService = Depends(get_task_service),
    categories: CategoryService = Depends(get_category_service),
    memory_service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> TaskResponse:
    retrieval_scope = await _resolve_retrieval_scope(payload.scope, categories)
    if retrieval_scope is not None and not retrieval_scope.get("document_ids"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="所选知识库范围里没有任何文档，请重新选择或改用全部知识库",
        )

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
        retrieval_scope=retrieval_scope,  # type: ignore[arg-type]
        depth=payload.depth,
        use_skills=payload.use_skills,
    )
    result = task_result(state, max_retries=service.max_retries, usage=service.last_usage)
    await _maybe_extract_memories(
        memory_service, user_id, query=payload.query, result=result, task_id=task_id
    )
    return TaskResponse.model_validate(result)


def _to_summary(record: Any) -> TaskSummaryOut:
    result = record.result or {}
    return TaskSummaryOut(
        task_id=record.task_id,
        query=record.query,
        status=record.status,
        mode=result.get("mode"),
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


def _resumable(status_value: str, snapshot: dict | None) -> bool:
    """是否可以从断点继续：未完成的中断任务 + 存在未完成的检查点。"""
    if status_value not in {"failed", "cancelled"} or snapshot is None:
        return False
    if snapshot.get("is_complete"):
        return False
    return snapshot.get("task_status") != "completed"


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    task_id: str,
    repository: TaskRepository = Depends(get_task_repository),
    store: CheckpointStore | None = Depends(get_checkpoint_store),
) -> TaskDetailResponse:
    record = await repository.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    snapshot = await store.snapshot(task_id) if store is not None else None
    attempts = await repository.list_attempts(task_id)
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
            "running": record.status == "running",
            "resumable": _resumable(record.status, snapshot),
            "attempts": [
                {
                    "attempt_no": item.attempt_no,
                    "status": item.status,
                    "started_at": item.started_at,
                    "finished_at": item.finished_at,
                    "error_type": item.error_type,
                    "retry_count": item.retry_count,
                }
                for item in attempts
            ],
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


@router.post("/tasks/{task_id}/cancel", response_model=CancelTaskResponse)
async def cancel_task(
    task_id: str,
    registry: TaskRegistry = Depends(get_task_registry),
) -> CancelTaskResponse:
    """取消正在运行的任务（会同时中断进行中的模型调用）。

    说明：运行状态保存在进程内存中，因此仅对**本进程**正在执行的任务有效；
    已完成 / 已取消 / 不存在的任务返回 404。
    """
    if not registry.cancel(task_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不在运行中（可能已完成、已取消或不存在）",
        )

    logger.info(
        "收到取消请求",
        extra={"task_id": task_id, "event": "task_cancel_requested", "status": "ok"},
    )
    return CancelTaskResponse(task_id=task_id, status="cancelling")


@router.post("/tasks/stream")
async def stream_task(
    request: Request,
    payload: TaskRequest,
    service: TaskService = Depends(get_task_service),
    categories: CategoryService = Depends(get_category_service),
    memory_service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    """以 SSE 推送 Agent 执行进度。

    前端不应展示模型隐藏推理过程。
    """
    task_id = str(uuid4())
    request.state.task_id = task_id

    retrieval_scope = await _resolve_retrieval_scope(payload.scope, categories)
    if retrieval_scope is not None and not retrieval_scope.get("document_ids"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="所选知识库范围里没有任何文档，请重新选择或改用全部知识库",
        )

    stored = await memory_service.get_preferences(user_id)
    preferences = {**stored, **(payload.user_preferences or {})}
    completed: dict = {}

    async def event_source() -> AsyncIterator[str]:
        async for event in service.stream(
            payload.query,
            user_preferences=preferences,
            task_id=task_id,
            user_id=user_id,
            retrieval_scope=retrieval_scope,  # type: ignore[arg-type]
            depth=payload.depth,
            use_skills=payload.use_skills,
        ):
            if event.get("event") == "task_completed" and event.get("result"):
                completed.update(event["result"])
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # 任务完成后提取长期记忆（仅长文；best-effort，失败不影响已推送的结果）
        if completed:
            await _maybe_extract_memories(
                memory_service, user_id, query=payload.query, result=completed, task_id=task_id
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/tasks/{task_id}/resume")
async def resume_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
    repository: TaskRepository = Depends(get_task_repository),
    store: CheckpointStore | None = Depends(get_checkpoint_store),
    memory_service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    """从断点继续执行被中断（失败/取消）的任务，SSE 协议与 /tasks/stream 一致。

    与「重新生成」的区别：这里复用同一 task_id 与 checkpoint，已完成的步骤
    不会重跑；没有可用检查点时返回 409，前端应改用重新生成。
    """
    record = await repository.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if record.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务正在运行中")

    snapshot = await store.snapshot(task_id) if store is not None else None
    if not _resumable(record.status, snapshot):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该任务没有可恢复的检查点，请使用「重新生成」",
        )

    stored = await memory_service.get_preferences(user_id)
    completed: dict = {}

    async def event_source() -> AsyncIterator[str]:
        async for event in service.resume(task_id, user_preferences=stored, user_id=user_id):
            if event.get("event") == "task_completed" and event.get("result"):
                completed.update(event["result"])
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        if completed:
            await _maybe_extract_memories(
                memory_service, user_id, query=record.query, result=completed, task_id=task_id
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/tasks/{task_id}/rerun")
async def rerun_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
    categories: CategoryService = Depends(get_category_service),
    repository: TaskRepository = Depends(get_task_repository),
    memory_service: MemoryService = Depends(get_memory_service),
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    """用同一 query **重新生成**：新建一次运行（新 task_id），原任务记录保持不变。

    这样「换模型/修好密钥后再试」的结果可以与原任务并列对比，不会覆盖历史。
    """
    record = await repository.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if record.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务正在运行中")

    new_task_id = str(uuid4())
    stored = await memory_service.get_preferences(user_id)
    completed: dict = {}

    # 重跑按原任务的范围**重新解析**：类别里新增的文档会被纳入（新一次运行）
    previous_scope = (record.result or {}).get("scope") or None
    rerun_scope = None
    if previous_scope and (
        previous_scope.get("category_ids") or previous_scope.get("selected_document_ids")
    ):
        rerun_scope = await _resolve_retrieval_scope(
            TaskScope(
                category_ids=list(previous_scope.get("category_ids") or []),
                document_ids=list(previous_scope.get("selected_document_ids") or []),
            ),
            categories,
        )

    async def event_source() -> AsyncIterator[str]:
        previous = record.result or {}
        previous_mode = previous.get("mode")
        rerun_depth = previous_mode if previous_mode in {"brief", "longform"} else "auto"
        async for event in service.stream(
            record.query,
            user_preferences=stored,
            task_id=new_task_id,
            user_id=user_id,
            retrieval_scope=rerun_scope,  # type: ignore[arg-type]
            depth=rerun_depth,
            use_skills=bool((previous.get("profile") or {}).get("allow_skills")),
        ):
            # 让前端知道这是一次重新生成（并指向原任务）
            if event.get("event") == "task_started":
                event = {**event, "rerun_of": task_id}
            if event.get("event") == "task_completed" and event.get("result"):
                completed.update(event["result"])
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        if completed:
            await _maybe_extract_memories(
                memory_service, user_id, query=record.query, result=completed, task_id=new_task_id
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
