"""FastAPI 依赖项。

把 Provider 通过依赖注入提供，测试时可用 ``app.dependency_overrides``
替换为假实现，从而无需真实 DeepSeek API（见 AGENTS.md §22）。
"""

from __future__ import annotations

from fastapi import Depends

from app.core.config import get_settings
from app.llm.base import LLMProvider
from app.llm.factory import get_llm
from app.services.task_service import TaskService


def get_llm_provider() -> LLMProvider:
    return get_llm()


def get_task_service(provider: LLMProvider = Depends(get_llm_provider)) -> TaskService:
    settings = get_settings()
    return TaskService(provider, max_retries=settings.max_retries)
