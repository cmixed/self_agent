from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_task_registry
from app.core.task_registry import TaskRegistry
from app.llm.base import ChatMessage, LLMProvider, LLMResponse
from app.main import create_app
from app.memory.repository import TaskRepository
from app.memory.sqlite import SqliteDatabase
from app.services.task_service import TaskService


class BlockingProvider(LLMProvider):
    """永远阻塞的假 Provider：用于验证取消能中断进行中的调用。"""

    name = "blocking"

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def chat(  # type: ignore[override]
        self, messages: list[ChatMessage], **kwargs: object
    ) -> LLMResponse:
        self.started.set()
        await asyncio.Event().wait()  # 直到被取消
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        return None


# --- 注册表 ---


async def test_registry_register_cancel_unregister() -> None:
    registry = TaskRegistry()
    dummy = asyncio.create_task(asyncio.sleep(30))
    try:
        assert registry.is_running("t1") is False
        assert registry.cancel("t1") is False

        registry.register("t1", dummy)
        assert registry.is_running("t1") is True
        assert registry.running_ids() == ["t1"]

        assert registry.cancel("t1") is True
        with contextlib.suppress(asyncio.CancelledError):
            await dummy
        assert dummy.cancelled()
        # 任务已结束 -> 不再视为运行中，重复取消返回 False
        assert registry.is_running("t1") is False
        assert registry.cancel("t1") is False
    finally:
        registry.unregister("t1")


async def test_registry_ignores_finished_task() -> None:
    registry = TaskRegistry()
    done = asyncio.create_task(asyncio.sleep(0))
    await done
    registry.register("t2", done)

    assert registry.is_running("t2") is False
    assert registry.cancel("t2") is False


# --- 仓储：cancelled 落库 ---


async def test_cancel_run_marks_cancelled_and_is_idempotent(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    repository = TaskRepository(database)

    await repository.start_run(task_id="t1", user_id="u1", query="q")
    await repository.cancel_run(task_id="t1")

    record = await repository.get_task("t1")
    assert record is not None
    assert record.status == "cancelled"
    assert record.error_type == "task_cancelled"
    assert record.finished_at is not None

    # 幂等
    await repository.cancel_run(task_id="t1")
    assert (await repository.get_task("t1")).status == "cancelled"  # type: ignore[union-attr]


async def test_cancel_run_does_not_overwrite_completed(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    repository = TaskRepository(database)

    await repository.start_run(task_id="t2", user_id="u1", query="q")
    await repository.finish_run(task_id="t2", result={"status": "completed"})
    await repository.cancel_run(task_id="t2")

    record = await repository.get_task("t2")
    assert record is not None
    assert record.status == "completed"


# --- 服务：取消后自动落库 ---


async def test_service_marks_run_cancelled_when_task_is_cancelled(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    repository = TaskRepository(database)
    registry = TaskRegistry()
    provider = BlockingProvider()
    service = TaskService(provider, repository=repository, registry=registry, max_retries=0)
    task_id = "t-cancel-service"

    async def consume() -> None:
        async for _ in service.stream("写一篇综述", task_id=task_id, user_id="u1"):
            pass

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(provider.started.wait(), timeout=5)

    assert registry.is_running(task_id) is True
    assert registry.cancel(task_id) is True

    with contextlib.suppress(asyncio.CancelledError):
        await consumer

    # 结论：被取消的任务不再停留在 running，而是 cancelled
    record = await repository.get_task(task_id)
    assert record is not None
    assert record.status == "cancelled"
    assert record.error_type == "task_cancelled"
    assert registry.is_running(task_id) is False


# --- 接口 ---


async def test_cancel_endpoint_cancels_registered_task() -> None:
    registry = TaskRegistry()
    app = create_app()
    app.dependency_overrides[get_task_registry] = lambda: registry

    dummy = asyncio.create_task(asyncio.sleep(30))
    registry.register("t-x", dummy)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/tasks/t-x/cancel")

    assert response.status_code == 200
    assert response.json() == {"task_id": "t-x", "status": "cancelling"}

    with contextlib.suppress(asyncio.CancelledError):
        await dummy
    assert dummy.cancelled()


@pytest.mark.parametrize("task_id", ["not-running", "already-done"])
async def test_cancel_endpoint_returns_404_when_not_running(task_id: str) -> None:
    app = create_app()
    # 用一个空的注册表，模拟「任务不在运行中」（FastAPI 会无参调用它）
    app.dependency_overrides[get_task_registry] = TaskRegistry

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/tasks/{task_id}/cancel")

    assert response.status_code == 404
    assert "不在运行中" in response.json()["detail"]
