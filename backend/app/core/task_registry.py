"""正在运行任务的注册表（用于主动取消）。

SSE / 同步任务都在请求协程里驱动 Agent Graph，进程内没有其他地方能引用到它，
因此这里登记 ``task_id -> asyncio.Task``，取消接口据此精确取消整条执行链
（会同时取消进行中的上游 HTTP 请求）。

注意：状态保存在**进程内存**中，因此仅适用于单进程部署（本项目为本地单 worker）。
多 worker 场景需要换成共享存储 / 消息总线。
"""

from __future__ import annotations

import asyncio
from typing import Any

_registry: TaskRegistry | None = None


class TaskRegistry:
    """进程内正在运行任务的注册表。"""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}

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
