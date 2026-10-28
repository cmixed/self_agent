"""导入预览 token 的通用内存存储。

预设 / 长期记忆 / 知识库都采用「上传 → 预览 → 确认」两段式：
预览结果暂存在进程内存中，确认时一次性消费 token。进程重启会丢失预览，
这是预期行为（未确认的导入不应在重启后自动生效）。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from uuid import uuid4

from app.transfer.errors import ImportPreviewExpiredError

DEFAULT_PREVIEW_TTL_SECONDS = 600


@dataclass(frozen=True)
class PendingPreview[T]:
    token: str
    payload: T
    expires_at: float


class PreviewStore[T]:
    """带 TTL 的预览存储；token 一次性使用。"""

    def __init__(self, *, ttl_seconds: float = DEFAULT_PREVIEW_TTL_SECONDS) -> None:
        self._ttl_seconds = max(0.001, ttl_seconds)
        self._pending: dict[str, PendingPreview[T]] = {}
        self._lock = asyncio.Lock()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    async def put(self, payload: T) -> PendingPreview[T]:
        token = uuid4().hex
        preview = PendingPreview(
            token=token,
            payload=payload,
            expires_at=time.monotonic() + self._ttl_seconds,
        )
        async with self._lock:
            self._cleanup_expired()
            self._pending[token] = preview
        return preview

    async def pop(self, token: str, *, expired_message: str) -> T:
        async with self._lock:
            self._cleanup_expired()
            preview = self._pending.pop(token, None)
        if preview is None:
            raise ImportPreviewExpiredError(expired_message)
        return preview.payload

    def _cleanup_expired(self) -> None:
        now = time.monotonic()
        expired = [token for token, item in self._pending.items() if item.expires_at <= now]
        for token in expired:
            self._pending.pop(token, None)
