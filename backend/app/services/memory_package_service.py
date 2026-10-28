"""长期记忆包（JSON）：偏好 + 记忆的导出、预览与合并导入。

合并策略与自动提取一致：**显式已有偏好优先**，不覆盖；记忆按
``app/memory/dedupe.py`` 的确定性规则去重。因此重复导入同一个备份不会
产生重复记录。导入的 ``kind=preference`` 会降级为 ``fact``（偏好只走
``user_preferences``，不在两张表里各存一份）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.memory.dedupe import canonical_preference_key, matches_any
from app.memory.repository import MemoryRecord
from app.services.memory_service import MemoryService
from app.transfer.errors import ImportPackageError, ImportPackageTooLargeError
from app.transfer.package import decode_json, encode_json
from app.transfer.preview import PreviewStore

logger = get_logger(__name__)

PACKAGE_FORMAT = "self-agent-memory"
PACKAGE_VERSION = 1
MAX_PACKAGE_BYTES = 1 * 1024 * 1024
MAX_PREFERENCES = 100
MAX_MEMORIES = 500
MAX_PREFERENCE_KEY_LENGTH = 40
MAX_PREFERENCE_VALUE_LENGTH = 200
MAX_MEMORY_KIND_LENGTH = 40
MAX_MEMORY_CONTENT_LENGTH = 300
VALID_MEMORY_KINDS = {"fact", "task_type"}


@dataclass(frozen=True)
class MemoryPackage:
    preferences: dict[str, str]
    memories: list[MemoryPackageItem]
    warnings: list[str]
    source_filename: str | None = None


@dataclass(frozen=True)
class MemoryPackageItem:
    kind: str
    content: str


@dataclass(frozen=True)
class MemoryPackagePreview:
    preferences: dict[str, str]
    memories: list[MemoryPackageItem]
    skipped_preferences: list[str] = field(default_factory=list)
    skipped_memories: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_filename: str | None = None


@dataclass(frozen=True)
class MemoryImportResult:
    preferences: list[str]
    memories: list[str]
    skipped_preferences: list[str]
    skipped_memories: list[str]


def parse_memory_package(data: bytes, *, filename: str | None = None) -> MemoryPackage:
    """解析并校验长期记忆 JSON。"""
    if len(data) > MAX_PACKAGE_BYTES:
        raise ImportPackageTooLargeError(
            f"记忆文件超过 {MAX_PACKAGE_BYTES // (1024 * 1024)} MB 限制"
        )
    payload = decode_json(data, error_message="记忆文件不是有效的 JSON")
    if not isinstance(payload, dict):
        raise ImportPackageError("记忆文件顶层必须是对象")

    package_format = payload.get("format")
    if package_format is not None and package_format != PACKAGE_FORMAT:
        raise ImportPackageError(f"不支持的记忆文件格式：{package_format}")
    version = payload.get("version", PACKAGE_VERSION)
    if not isinstance(version, int) or version < 1:
        raise ImportPackageError("记忆文件版本号不合法")
    if version > PACKAGE_VERSION:
        raise ImportPackageError("记忆文件版本过新，请升级应用后再导入")

    warnings: list[str] = []
    raw_preferences = payload.get("preferences", {})
    if not isinstance(raw_preferences, dict):
        raise ImportPackageError("preferences 必须是键值对象")
    if len(raw_preferences) > MAX_PREFERENCES:
        raise ImportPackageTooLargeError(f"一次最多导入 {MAX_PREFERENCES} 条偏好")
    preferences: dict[str, str] = {}
    for raw_key, raw_value in raw_preferences.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str):
            warnings.append("偏好中存在非字符串键值，已忽略")
            continue
        key = raw_key.strip()
        value = raw_value.strip()
        if not key or not value:
            warnings.append("偏好中存在空键或空值，已忽略")
            continue
        if len(key) > MAX_PREFERENCE_KEY_LENGTH:
            raise ImportPackageError(f"偏好键「{key[:20]}…」超过 {MAX_PREFERENCE_KEY_LENGTH} 字")
        if len(value) > MAX_PREFERENCE_VALUE_LENGTH:
            raise ImportPackageError(f"偏好「{key}」的值超过 {MAX_PREFERENCE_VALUE_LENGTH} 字")
        preferences[key] = value

    raw_memories = payload.get("memories", [])
    if not isinstance(raw_memories, list):
        raise ImportPackageError("memories 必须是数组")
    if len(raw_memories) > MAX_MEMORIES:
        raise ImportPackageTooLargeError(f"一次最多导入 {MAX_MEMORIES} 条记忆")
    memories: list[MemoryPackageItem] = []
    for index, raw in enumerate(raw_memories, 1):
        if not isinstance(raw, dict):
            raise ImportPackageError(f"第 {index} 条记忆不是对象")
        content = raw.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ImportPackageError(f"第 {index} 条记忆缺少内容")
        content = content.strip()
        if len(content) > MAX_MEMORY_CONTENT_LENGTH:
            raise ImportPackageError(f"第 {index} 条记忆超过 {MAX_MEMORY_CONTENT_LENGTH} 字")
        kind = raw.get("kind", "fact")
        if not isinstance(kind, str) or not kind.strip():
            kind = "fact"
        kind = kind.strip()
        if len(kind) > MAX_MEMORY_KIND_LENGTH:
            kind = "fact"
        if kind == "preference":
            warnings.append(f"第 {index} 条记忆类型为 preference，已改为 fact")
            kind = "fact"
        elif kind not in VALID_MEMORY_KINDS:
            warnings.append(f"第 {index} 条记忆类型「{kind}」未知，已改为 fact")
            kind = "fact"
        memories.append(MemoryPackageItem(kind=kind, content=content))

    if filename and len(filename) > 260:
        filename = filename[:260]
    return MemoryPackage(
        preferences=preferences,
        memories=memories,
        warnings=warnings,
        source_filename=filename,
    )


def dump_memory_package(
    preferences: dict[str, str],
    memories: list[MemoryRecord],
) -> bytes:
    payload = {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "preferences": dict(preferences),
        "memories": [
            {"kind": item.kind, "content": item.content, "created_at": item.created_at}
            for item in memories
        ],
    }
    return encode_json(payload)


class MemoryPackageService:
    """长期记忆导出与合并导入（预览 token 内存暂存）。"""

    def __init__(self, memory: MemoryService, *, ttl_seconds: float = 600) -> None:
        self._memory = memory
        self._previews: PreviewStore[MemoryPackagePreview] = PreviewStore(ttl_seconds=ttl_seconds)

    @property
    def ttl_seconds(self) -> float:
        return self._previews.ttl_seconds

    async def preview(
        self, user_id: str, data: bytes, *, filename: str | None = None
    ) -> tuple[str, MemoryPackagePreview]:
        package = await asyncio.to_thread(parse_memory_package, data, filename=filename)
        preferences, memories = await self._memory.get_profile(user_id)
        known_preference_values = list(preferences.values())
        known_memory_values = [item.content for item in memories]
        known_values = [*known_preference_values, *known_memory_values]

        warnings = list(package.warnings)
        selected_preferences: dict[str, str] = {}
        skipped_preferences: list[str] = []
        for raw_key, value in package.preferences.items():
            key = canonical_preference_key(raw_key) or raw_key.strip()
            if key in preferences or key in selected_preferences:
                skipped_preferences.append(key)
                continue
            if matches_any(value, known_values):
                skipped_preferences.append(key)
                continue
            selected_preferences[key] = value
            known_values.append(value)

        selected_memories: list[MemoryPackageItem] = []
        skipped_memories: list[str] = []
        known_texts = list(known_values)
        for item in package.memories:
            if matches_any(item.content, known_texts):
                skipped_memories.append(item.content)
                continue
            selected_memories.append(item)
            known_texts.append(item.content)

        preview = MemoryPackagePreview(
            preferences=selected_preferences,
            memories=selected_memories,
            skipped_preferences=skipped_preferences,
            skipped_memories=skipped_memories,
            warnings=warnings,
            source_filename=package.source_filename,
        )
        pending = await self._previews.put(preview)
        return pending.token, preview

    async def confirm(self, user_id: str, token: str) -> MemoryImportResult:
        preview = await self._previews.pop(
            token, expired_message="导入预览已过期，请重新上传记忆文件"
        )
        # 预览到确认之间可能新增了偏好/记忆：再次读取并只写入真正的新项
        preferences, memories = await self._memory.get_profile(user_id)
        known_values = [*preferences.values(), *(item.content for item in memories)]

        imported_preferences: list[str] = []
        skipped_preferences = list(preview.skipped_preferences)
        for key, value in preview.preferences.items():
            if key in preferences or matches_any(value, known_values):
                skipped_preferences.append(key)
                continue
            await self._memory.set_preference(user_id, key, value)
            preferences[key] = value
            known_values.append(value)
            imported_preferences.append(key)

        imported_memories: list[str] = []
        skipped_memories = list(preview.skipped_memories)
        known_texts = list(known_values)
        for item in preview.memories:
            if matches_any(item.content, known_texts):
                skipped_memories.append(item.content)
                continue
            record = await self._memory.add_memory(user_id, kind=item.kind, content=item.content)
            if record is None:
                skipped_memories.append(item.content)
                continue
            imported_memories.append(item.content)
            known_texts.append(item.content)

        logger.info(
            "长期记忆已导入",
            extra={
                "event": "memory_imported",
                "status": "ok",
                "preferences": len(imported_preferences),
                "memories": len(imported_memories),
            },
        )
        return MemoryImportResult(
            preferences=imported_preferences,
            memories=imported_memories,
            skipped_preferences=skipped_preferences,
            skipped_memories=skipped_memories,
        )

    async def export_all(self, user_id: str) -> bytes:
        preferences, memories = await self._memory.get_profile(user_id)
        return await asyncio.to_thread(dump_memory_package, preferences, memories)


__all__ = [
    "MAX_PACKAGE_BYTES",
    "MemoryImportResult",
    "MemoryPackageItem",
    "MemoryPackagePreview",
    "MemoryPackageService",
    "dump_memory_package",
    "parse_memory_package",
]
