"""LangGraph Checkpoint（短期记忆）。

与业务数据分离存放（AGENTS.md §13）：

- ``app.db``：任务记录与长期记忆（业务数据）；
- ``checkpoints.db``：LangGraph 的 Agent checkpoint（短期记忆 / 可恢复）。

线程 id 使用 ``task_id``，因此可以按任务回溯 Agent 各阶段的落盘状态。
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# AgentState.messages 里是自定义 Pydantic 类型 ChatMessage；checkpoint 反序列化时
# 需要显式登记，否则 LangGraph 会告警（未来版本会直接阻止）。只登记我们自己的类型，
# 不放开其他自定义类型，为未来的严格模式做好准备。
_CHECKPOINT_SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[("app.llm.base", "ChatMessage")],
)


class CheckpointStore:
    """管理 AsyncSqliteSaver 的打开与关闭（生命周期由应用 lifespan 控制）。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: aiosqlite.Connection | None = None
        self._saver: AsyncSqliteSaver | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def saver(self) -> AsyncSqliteSaver | None:
        return self._saver

    async def start(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self._path)
        self._saver = AsyncSqliteSaver(self._connection, serde=_CHECKPOINT_SERDE)
        await self._saver.setup()

    async def snapshot(self, thread_id: str) -> dict | None:
        """返回该 thread 最近的 checkpoint 状态值（无记录时 None）。

        用于两件事：判断任务是否「可继续生成」；续跑前给前端一份进度快照。
        """
        if self._saver is None:
            return None
        checkpoint_tuple = await self._saver.aget_tuple(
            {"configurable": {"thread_id": thread_id}}
        )
        if checkpoint_tuple is None:
            return None
        checkpoint = checkpoint_tuple.checkpoint or {}
        values = checkpoint.get("channel_values")
        return values if isinstance(values, dict) else {}

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self._saver = None
