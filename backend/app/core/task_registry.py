"""正在运行任务的注册表与事件通道（用于主动取消与断线重连）。

两类进程内状态：

- ``_tasks``：``task_id -> asyncio.Task``。SSE / 同步任务都在**后台任务**里驱动
  Agent Graph（与浏览器连接解耦），取消接口据此精确取消整条执行链
  （会同时取消进行中的上游 HTTP 请求）。
- ``_channels``：``task_id -> TaskChannel``。每次任务执行的事件先写入缓冲区，
  再由任意数量的 SSE 订阅者回放 + 跟随。前端刷新页面后重新订阅即可完整重建
  进度（AGENTS.md §19）。

注意：两类状态都保存在**进程内存**中，仅适用于单进程部署（本项目为本地单
worker）。多 worker / 重启恢复需要共享存储或事件日志。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

# 已结束任务的 channel 保留数量：用于「刚结束就刷新」时完整回放；
# 更早的任务由 SQLite 结果合成终态事件。
MAX_RETAINED_CHANNELS = 20

_registry: TaskRegistry | None = None


class TaskChannel:
    """单个任务的事件通道：缓冲 + 多订阅者广播。

    ``follow()`` 先回放已缓冲事件，再跟随新事件，直到 ``close()``。
    """

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._condition = asyncio.Condition()
        self._closed = False
        self.last_event: dict[str, Any] | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    async def publish(self, event: dict[str, Any]) -> None:
        if self._closed:
            return
        self.last_event = event
        async with self._condition:
            self._events.append(event)
            self._condition.notify_all()

    async def close(self) -> None:
        self._closed = True
        async with self._condition:
            self._condition.notify_all()

    async def follow(self) -> AsyncIterator[dict[str, Any]]:
        """回放 + 跟随；通道关闭且事件耗尽后结束。"""
        index = 0
        while True:
            async with self._condition:
                while index >= len(self._events) and not self._closed:
                    await self._condition.wait()
                batch = self._events[index:]
                index = len(self._events)
            for event in batch:
                yield event
            if self._closed and index >= len(self._events):
                return


class TaskRegistry:
    """进程内正在运行任务的注册表（任务句柄 + 事件通道）。"""

    def __init__(self, *, max_retained: int = MAX_RETAINED_CHANNELS) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._channels: dict[str, TaskChannel] = {}
        # 已结束任务的 FIFO（用于保留上限淘汰）
        self._finished: OrderedDict[str, None] = OrderedDict()
        self._max_retained = max(1, max_retained)

    # --- 任务句柄（取消） ---

    def register(self, task_id: str, task: asyncio.Task[Any] | None) -> None:
        if task is not None:
            self._tasks[task_id] = task

    def unregister(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def is_running(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        return task is not None and not task.done()

    def cancel(self, task_id: str) -> bool:
        """请求取消；返回是否真的发出了取消信号。"""
        task = self._tasks.get(task_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def running_ids(self) -> list[str]:
        return [task_id for task_id in self._tasks if self.is_running(task_id)]

    async def shutdown(self) -> None:
        """应用关闭时取消所有后台任务并等待退出。"""
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # --- 事件通道（观察 / 回放） ---

    def start(self, task_id: str, coro: Any) -> asyncio.Task[Any]:
        """启动一次运行并立即登记（保证 cancel 能在服务注册前命中）。

        **总是新建事件通道**：续跑会复用同一个 ``task_id``，若沿用上一次的
        已关闭通道，新事件会被丢弃、订阅者只会看到上一次的旧事件（并以旧终态
        结束）。重跑虽然换 ``task_id``，也一并走同一条路径。
        """
        previous = self._channels.get(task_id)
        if previous is not None:
            # 上一次运行可能还有订阅者挂在旧通道上：显式结束，避免它们永远等待
            with contextlib.suppress(RuntimeError):
                asyncio.create_task(previous.close())
        self._channels.pop(task_id, None)
        self._finished.pop(task_id, None)
        self._channels[task_id] = TaskChannel()
        task = asyncio.create_task(coro)
        self.register(task_id, task)
        return task

    def ensure_channel(self, task_id: str) -> TaskChannel:
        channel = self._channels.get(task_id)
        if channel is None:
            channel = TaskChannel()
            self._channels[task_id] = channel
        return channel

    def channel(self, task_id: str) -> TaskChannel | None:
        return self._channels.get(task_id)

    async def publish(self, task_id: str, event: dict[str, Any]) -> None:
        await self.ensure_channel(task_id).publish(event)

    async def close(self, task_id: str) -> None:
        """结束任务的通道：唤醒所有订阅者，并把通道放入保留队列。"""
        channel = self._channels.get(task_id)
        if channel is None:
            return
        await channel.close()
        self._finished[task_id] = None
        self._finished.move_to_end(task_id)
        while len(self._finished) > self._max_retained:
            oldest, _ = self._finished.popitem(last=False)
            self._channels.pop(oldest, None)

    def last_event(self, task_id: str) -> dict[str, Any] | None:
        """最近一条事件（顶栏胶囊展示阶段用）。"""
        channel = self._channels.get(task_id)
        return channel.last_event if channel is not None else None


def get_task_registry() -> TaskRegistry:
    """返回进程级注册表。"""
    global _registry
    if _registry is None:
        _registry = TaskRegistry()
    return _registry


def reset_task_registry() -> None:
    """仅用于测试：清空注册表。"""
    global _registry
    _registry = None
