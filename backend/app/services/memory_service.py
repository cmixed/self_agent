"""长期记忆服务（AGENTS.md §14）。

区分两类长期记忆：
- **偏好**（``user_preferences``）：写作风格 / 输出格式 / 语言 / 常见任务类型等键值；
- **记忆**（``memories``）：跨会话有价值的自由文本事实。

写入方式：
1. 显式 API（用户或前端主动设置）；
2. 任务结束后用一次结构化 LLM 调用自动提取（best-effort，失败不影响任务本身）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMError, LLMProvider
from app.memory.repository import MemoryRecord, MemoryRepository

logger = get_logger(__name__)

PreferenceKind = Literal["preference", "fact", "task_type"]

# 常用偏好键（§14）；允许其他键，但提示模型优先使用这些
COMMON_PREFERENCE_KEYS = ("style", "format", "language", "task_types")

_MAX_ANSWER_CHARS = 1500

_EXTRACT_SYSTEM_PROMPT = """你负责从一次任务交互中提取**长期有效**的用户信息。

只提取跨任务仍然成立、且对将来有帮助的信息，例如：
- 写作风格偏好（style）：如"偏好学术严谨"、"喜欢简洁直述"；
- 输出格式偏好（format）：如"要求 Markdown"、"需要参考来源列表"；
- 语言偏好（language）：如"使用中文"；
- 常见任务类型（task_types）：如"经常撰写技术综述"。

**不要**提取：本次任务的具体内容、一次性事实、可从任务记录中直接读到的信息。

只输出 JSON：
{"preferences": [{"key": "style", "value": "偏好学术严谨"}],
 "memories": [{"kind": "preference|fact|task_type", "content": "..."}]}

如果本次交互没有值得长期保存的信息，两个数组都返回空。
"""


class PreferenceItemModel(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=200)


class MemoryItemModel(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=300)


class MemoryExtractionModel(BaseModel):
    """结构化提取结果。"""

    preferences: list[PreferenceItemModel] = Field(default_factory=list, max_length=4)
    memories: list[MemoryItemModel] = Field(default_factory=list, max_length=4)


class MemoryService:
    """长期记忆的查询、显式写入与自动提取。"""

    def __init__(self, repository: MemoryRepository, llm: LLMProvider | None = None) -> None:
        self._repository = repository
        self._llm = llm

    # --- 读取 ---

    async def get_preferences(self, user_id: str) -> dict[str, str]:
        return await self._repository.get_preferences(user_id)

    async def get_profile(self, user_id: str) -> tuple[dict[str, str], list[MemoryRecord]]:
        preferences = await self._repository.get_preferences(user_id)
        memories = await self._repository.list_memories(user_id)
        return preferences, memories

    # --- 显式写入 ---

    async def set_preference(self, user_id: str, key: str, value: str) -> None:
        await self._repository.set_preference(user_id, key, value)

    async def delete_preference(self, user_id: str, key: str) -> bool:
        return await self._repository.delete_preference(user_id, key)

    async def add_memory(
        self,
        user_id: str,
        *,
        kind: str,
        content: str,
        source_task_id: str | None = None,
    ) -> MemoryRecord | None:
        return await self._repository.add_memory(
            user_id, kind=kind, content=content, source_task_id=source_task_id
        )

    async def delete_memory(self, user_id: str, memory_id: int) -> bool:
        return await self._repository.delete_memory(user_id, memory_id)

    # --- 自动提取 ---

    async def extract_from_task(
        self,
        user_id: str,
        *,
        query: str,
        result: dict,
        task_id: str | None = None,
    ) -> MemoryExtractionModel | None:
        """从一次已完成的任务中提取长期记忆。

        best-effort：任何失败只记日志，绝不影响任务本身。
        """
        if self._llm is None or not query.strip():
            return None

        answer = str(result.get("final_answer") or "")[:_MAX_ANSWER_CHARS]
        messages = [
            ChatMessage(role="system", content=_EXTRACT_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=f"用户任务：{query}\n\n最终结果（截断）：\n{answer}",
            ),
        ]

        try:
            extracted = await self._llm.chat_structured(
                messages, MemoryExtractionModel, temperature=0.0, max_retries=0
            )
        except LLMError as exc:
            logger.warning(
                "长期记忆提取失败（忽略）",
                extra={
                    "task_id": task_id,
                    "event": "memory_extraction_failed",
                    "status": "error",
                    "error_type": exc.error_type,
                },
            )
            return None

        # 自动提取不得覆盖已有偏好：显式设置的值优先（用户可通过 API 主动更新）
        existing = await self._repository.get_preferences(user_id)
        for item in extracted.preferences:
            if item.key in existing:
                logger.info(
                    "跳过已存在的偏好键",
                    extra={
                        "task_id": task_id,
                        "event": "memory_preference_skipped",
                        "status": "ok",
                        "node": item.key,
                    },
                )
                continue
            await self._repository.set_preference(user_id, item.key, item.value)
            existing[item.key] = item.value

        for memory in extracted.memories:
            await self._repository.add_memory(
                user_id,
                kind=memory.kind,
                content=memory.content,
                source_task_id=task_id,
            )

        counts = f"preferences={len(extracted.preferences)} memories={len(extracted.memories)}"
        logger.info(
            "长期记忆已更新",
            extra={
                "task_id": task_id,
                "event": "memory_extracted",
                "status": "ok",
                "node": counts,
            },
        )
        return extracted


__all__ = [
    "COMMON_PREFERENCE_KEYS",
    "MemoryExtractionModel",
    "MemoryService",
    "PreferenceKind",
]
