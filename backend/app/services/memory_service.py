"""长期记忆服务（AGENTS.md §14）。

区分两类长期记忆：
- **偏好**（``user_preferences``）：写作风格 / 输出格式 / 语言 / 常见任务类型等键值；
- **记忆**（``memories``）：跨会话有价值的自由文本事实。

写入方式：
1. 显式 API（用户或前端主动设置）；
2. 任务结束后用一次结构化 LLM 调用自动提取（best-effort，失败不影响任务本身）。

去重分三层（``app/memory/dedupe.py``）：
1. 提取前把已有偏好/记忆放进提示词，让模型自己避免重复；
2. 偏好键归一化（``写作风格`` → ``style``），键或值重复则跳过；
3. 记忆归一化后与已有偏好值、已有记忆比较，近似重复直接跳过。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMError, LLMProvider
from app.memory.dedupe import canonical_preference_key, matches_any
from app.memory.repository import MemoryRecord, MemoryRepository
from app.prompts import render_prompt

logger = get_logger(__name__)

PreferenceKind = Literal["preference", "fact", "task_type"]

# 常用偏好键（§14）；允许其他键，但提示模型优先使用这些
COMMON_PREFERENCE_KEYS = ("style", "format", "language", "task_types")

_MAX_ANSWER_CHARS = 1500
# 提示词里最多回显多少条已有记忆（避免长文任务把上下文撑大）
_PROMPT_MEMORY_LIMIT = 20
_PROMPT_MEMORY_CHARS = 120

_EXTRACT_SYSTEM_PROMPT = render_prompt("memory_extract.md")


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


def _render_existing_memory(preferences: dict[str, str], memories: list[MemoryRecord]) -> str:
    """把已有长期记忆压缩成提示词片段，供模型自查重复。"""
    lines = ["已有长期记忆（不要重复提取；语义相同、只是换了说法也算重复）："]
    if preferences:
        rendered = "；".join(f"{key}={value}" for key, value in preferences.items())
        lines.append(f"偏好：{rendered}")
    else:
        lines.append("偏好：（无）")

    if memories:
        lines.append("记忆：")
        for memory in memories[:_PROMPT_MEMORY_LIMIT]:
            content = memory.content.strip()
            if len(content) > _PROMPT_MEMORY_CHARS:
                content = f"{content[:_PROMPT_MEMORY_CHARS]}…"
            lines.append(f"- [{memory.kind}] {content}")
        if len(memories) > _PROMPT_MEMORY_LIMIT:
            lines.append(f"- （另有 {len(memories) - _PROMPT_MEMORY_LIMIT} 条未列出）")
    else:
        lines.append("记忆：（无）")
    return "\n".join(lines)


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
        # 键归一化：``写作风格`` / ``Style`` 与 ``style`` 落到同一个键
        await self._repository.set_preference(
            user_id, canonical_preference_key(key) or key.strip(), value.strip()
        )

    async def delete_preference(self, user_id: str, key: str) -> bool:
        canonical = canonical_preference_key(key) or key.strip()
        if await self._repository.delete_preference(user_id, canonical):
            return True
        # 兼容归一化之前写入的旧键
        return canonical != key and await self._repository.delete_preference(user_id, key)

    async def add_memory(
        self,
        user_id: str,
        *,
        kind: str,
        content: str,
        source_task_id: str | None = None,
    ) -> MemoryRecord | None:
        """新增记忆；与已有记忆/偏好近似重复时返回 None。"""
        normalized = content.strip()
        if not normalized:
            return None

        preferences = await self._repository.get_preferences(user_id)
        memories = await self._repository.list_memories(user_id, limit=None)
        if matches_any(normalized, (memory.content for memory in memories)):
            return None
        if matches_any(normalized, preferences.values()):
            return None
        return await self._repository.add_memory(
            user_id, kind=kind, content=normalized, source_task_id=source_task_id
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

        existing_preferences = await self._repository.get_preferences(user_id)
        existing_memories = await self._repository.list_memories(user_id, limit=None)

        answer = str(result.get("final_answer") or "")[:_MAX_ANSWER_CHARS]
        messages = [
            ChatMessage(role="system", content=_EXTRACT_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=(
                    f"用户任务：{query}\n\n"
                    f"最终结果（截断）：\n{answer}\n\n"
                    f"{_render_existing_memory(existing_preferences, existing_memories)}"
                ),
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

        preferences_written = await self._apply_preferences(
            user_id, extracted.preferences, existing_preferences, task_id=task_id
        )
        memories_written = await self._apply_memories(
            user_id,
            extracted.memories,
            preferences=existing_preferences,
            memories=existing_memories,
            task_id=task_id,
        )

        counts = (
            f"preferences={preferences_written}/{len(extracted.preferences)} "
            f"memories={memories_written}/{len(extracted.memories)}"
        )
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

    async def _apply_preferences(
        self,
        user_id: str,
        items: list[PreferenceItemModel],
        existing: dict[str, str],
        *,
        task_id: str | None,
    ) -> int:
        """写入偏好：键归一化后去重；已有键/值一律不覆盖（显式设置优先）。"""
        written = 0
        for item in items:
            key = canonical_preference_key(item.key)
            value = item.value.strip()
            if not key or not value:
                continue
            if key in existing:
                self._log_skip("memory_preference_skipped", task_id, key)
                continue
            if matches_any(value, existing.values()):
                self._log_skip("memory_preference_skipped", task_id, key)
                continue
            await self._repository.set_preference(user_id, key, value)
            existing[key] = value
            written += 1
        return written

    async def _apply_memories(
        self,
        user_id: str,
        items: list[MemoryItemModel],
        *,
        preferences: dict[str, str],
        memories: list[MemoryRecord],
        task_id: str | None,
    ) -> int:
        """写入记忆：与已有偏好值/记忆近似重复时跳过，避免跨任务累积。"""
        written = 0
        known: list[str] = [memory.content for memory in memories]
        known.extend(preferences.values())

        for item in items:
            content = item.content.strip()
            if not content:
                continue
            if matches_any(content, known):
                self._log_skip("memory_duplicate_skipped", task_id, item.kind)
                continue

            kind = item.kind.strip() or "fact"
            if kind == "preference":
                # 契约要求偏好只走 preferences；模型越界时降级为事实，而不是
                # 在两张表里各留一条（用户看到的「重复记录」主要来自这里）。
                kind = "fact"
                self._log_skip("memory_kind_reclassified", task_id, "preference")

            record = await self._repository.add_memory(
                user_id, kind=kind, content=content, source_task_id=task_id
            )
            if record is None:
                self._log_skip("memory_duplicate_skipped", task_id, kind)
                continue
            known.append(content)
            written += 1
        return written

    @staticmethod
    def _log_skip(event: str, task_id: str | None, detail: str) -> None:
        logger.info(
            "跳过重复或越界的长期记忆",
            extra={
                "task_id": task_id,
                "event": event,
                "status": "ok",
                "node": detail,
            },
        )


__all__ = [
    "COMMON_PREFERENCE_KEYS",
    "MemoryExtractionModel",
    "MemoryService",
    "PreferenceKind",
]
