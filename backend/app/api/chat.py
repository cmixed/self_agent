"""对话接口（Phase 1：非流式）。

SSE 流式事件协议属于 Phase 2，与 LangGraph 一起实现（见 AGENTS.md §19）。
LLMError 由全局异常处理器统一映射（app/api/errors.py）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_llm_provider
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])
logger = get_logger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    provider: LLMProvider = Depends(get_llm_provider),
) -> ChatResponse:
    messages = [ChatMessage(role=m.role, content=m.content) for m in request.messages]

    result = await provider.chat(
        messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )

    logger.info(
        "chat 完成",
        extra={"event": "chat_completed", "status": "ok", "node": "llm"},
    )
    return ChatResponse(answer=result.content, model=result.model, usage=result.usage)
