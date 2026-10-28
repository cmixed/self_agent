"""把已完成任务的正文发送到用户邮箱（AGENTS.md §18 的任务动作）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import get_email_service, get_task_repository, get_user_id
from app.memory.repository import TaskRepository
from app.models.schemas import ErrorResponse, TaskEmailRequest, TaskEmailResponse
from app.services.email_service import (
    EmailAuthFailedError,
    EmailDeliveryError,
    EmailError,
    EmailInvalidRecipientError,
    EmailNotConfiguredError,
    EmailRecipientRejectedError,
    EmailService,
    EmailTooFrequentError,
    mask_email,
    normalize_recipient,
)

router = APIRouter(prefix="/api", tags=["email"])

# 领域异常 -> HTTP 状态码（错误体统一使用 ErrorResponse）
_EMAIL_ERROR_STATUS: dict[str, int] = {
    EmailNotConfiguredError.error_type: status.HTTP_503_SERVICE_UNAVAILABLE,
    EmailInvalidRecipientError.error_type: status.HTTP_400_BAD_REQUEST,
    EmailTooFrequentError.error_type: status.HTTP_429_TOO_MANY_REQUESTS,
    EmailAuthFailedError.error_type: status.HTTP_502_BAD_GATEWAY,
    EmailRecipientRejectedError.error_type: status.HTTP_400_BAD_REQUEST,
    EmailDeliveryError.error_type: status.HTTP_502_BAD_GATEWAY,
}


@router.post("/tasks/{task_id}/email", response_model=TaskEmailResponse)
async def send_task_email(
    task_id: str,
    payload: TaskEmailRequest,
    request: Request,
    repository: TaskRepository = Depends(get_task_repository),
    service: EmailService = Depends(get_email_service),
    user_id: str = Depends(get_user_id),
) -> TaskEmailResponse | JSONResponse:
    """只允许发送自己的、已完成且有正文的任务。

    未配置 SMTP 时返回 503；认证失败 / 网络异常返回 502；
    收件人格式错误返回 400，不会触发真实发信。
    """
    request.state.task_id = task_id
    record = await repository.get_task(task_id)
    # 不区分「不存在」与「不属于当前用户」，避免通过任务 ID 探测他人记录
    if record is None or record.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    result = record.result or {}
    answer = str(result.get("final_answer") or "")
    if record.status != "completed" or not answer.strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="任务尚未完成或没有可发送的正文",
        )

    try:
        recipient = normalize_recipient(payload.to)
        subject = await service.send_article(
            user_id=user_id,
            task_id=task_id,
            to=recipient,
            query=record.query,
            markdown=answer,
            finished_at=record.finished_at,
        )
    except EmailError as exc:
        body = ErrorResponse(
            error=exc.error_type,
            error_type=exc.error_type,
            detail=exc.message,
            task_id=task_id,
        )
        return JSONResponse(
            status_code=_EMAIL_ERROR_STATUS.get(exc.error_type, status.HTTP_502_BAD_GATEWAY),
            content=body.model_dump(),
        )

    return TaskEmailResponse(
        status="sent",
        task_id=task_id,
        to=mask_email(recipient),
        subject=subject,
    )
