"""任务执行与 SSE 订阅解耦的测试（AGENTS.md §19）。

关键回归：
- 浏览器断开（刷新页面）**不会**取消后台任务；
- 重新订阅时能从通道完整回放已经发生的事件；
- 通道已淘汰（进程重启 / 保留上限）时，用 SQLite 记录合成终态事件。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    build_database,
    get_task_registry,
    get_task_repository,
    get_task_service,
)
from app.core.task_registry import TaskChannel, TaskRegistry
from app.main import create_app
from app.memory.repository import TaskRepository
from app.memory.sqlite import SqliteDatabase


def _event(task_id: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"task_id": task_id, "event": name, "status": "running", **extra}


@pytest.fixture(autouse=True)
def _database() -> None:
    """ASGITransport 不触发 lifespan，这里显式建表（偏好 / 任务记录都要用到）。"""
    build_database().initialize()


class FakeStreamService:
    """可控的假 Service：按脚本逐条产出事件，用于验证与连接无关的执行。"""

    def __init__(self, *, steps: int = 6, delay: float = 0.02) -> None:
        self._steps = steps
        self._delay = delay
        self.finished = asyncio.Event()

    async def stream(self, query: str, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        task_id = str(kwargs["task_id"])
        yield _event(task_id, "task_started", message="开始执行")
        for index in range(self._steps):
            await asyncio.sleep(self._delay)
            yield _event(
                task_id,
                "writer_started",
                step=f"chapter_{index + 1}",
                message=f"正在撰写第 {index + 1} 章",
            )
        yield {
            "task_id": task_id,
            "event": "task_completed",
            "status": "completed",
            "message": "任务完成",
            "result": {"status": "completed", "final_answer": "正文"},
        }
        self.finished.set()


class FailingStreamService(FakeStreamService):
    async def stream(self, query: str, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        task_id = str(kwargs["task_id"])
        yield _event(task_id, "task_started")
        raise RuntimeError("boom")


async def _wait_until(predicate: Any, *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("等待条件超时")


def _parse_sse(body: str) -> list[dict[str, Any]]:
    frames = [line[len("data: ") :] for line in body.splitlines() if line.startswith("data: ")]
    return [json.loads(frame) for frame in frames]


# --- 通道 ---


async def test_channel_replays_buffered_events_then_follows() -> None:
    channel = TaskChannel()
    await channel.publish(_event("t1", "task_started"))
    await channel.publish(_event("t1", "planner_started"))

    received: list[str] = []

    async def consume() -> None:
        async for event in channel.follow():
            received.append(str(event["event"]))

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0)  # 让订阅者先跑一遍回放

    # 回放完毕后在「跟随」阶段发布的新事件也必须收到
    await channel.publish(_event("t1", "task_completed"))
    await channel.close()
    await asyncio.wait_for(consumer, timeout=5)

    assert received == ["task_started", "planner_started", "task_completed"]


async def test_channel_supports_multiple_subscribers() -> None:
    channel = TaskChannel()
    await channel.publish(_event("t1", "task_started"))

    async def consume() -> list[str]:
        return [str(event["event"]) async for event in channel.follow()]

    first = asyncio.create_task(consume())
    second = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await channel.publish(_event("t1", "task_completed"))
    await channel.close()

    assert await asyncio.wait_for(first, timeout=5) == ["task_started", "task_completed"]
    assert await asyncio.wait_for(second, timeout=5) == ["task_started", "task_completed"]


async def test_follow_finishes_on_already_closed_channel() -> None:
    channel = TaskChannel()
    await channel.publish(_event("t1", "task_started"))
    await channel.close()

    assert [event["event"] async for event in channel.follow()] == ["task_started"]


async def test_registry_start_replaces_stale_channel() -> None:
    """续跑复用同一 task_id：不能沿用上一次已关闭的通道（否则只回放旧事件）。"""
    registry = TaskRegistry()
    await registry.publish("t1", _event("t1", "task_failed"))
    await registry.close("t1")
    assert registry.channel("t1") is not None

    async def runner() -> None:
        await registry.publish("t1", _event("t1", "task_resumed"))
        await registry.close("t1")

    registry.start("t1", runner())
    await _wait_until(lambda: registry.channel("t1").closed)  # type: ignore[union-attr]

    events = [event["event"] async for event in registry.channel("t1").follow()]  # type: ignore[union-attr]
    assert events == ["task_resumed"]


async def test_registry_retains_only_recent_finished_channels() -> None:
    registry = TaskRegistry(max_retained=2)
    for index in range(4):
        task_id = f"t{index}"
        await registry.publish(task_id, _event(task_id, "task_completed"))
        await registry.close(task_id)

    assert registry.channel("t0") is None
    assert registry.channel("t1") is None
    assert registry.channel("t2") is not None
    assert registry.channel("t3") is not None


async def test_registry_shutdown_cancels_background_tasks() -> None:
    registry = TaskRegistry()
    started = asyncio.Event()

    async def runner() -> None:
        started.set()
        await asyncio.Event().wait()

    task = registry.start("t1", runner())
    await started.wait()

    await registry.shutdown()
    assert task.cancelled()


# --- 接口：观察已有任务 ---


async def _observe(app: Any, path: str) -> tuple[int, str]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
        return response.status_code, response.text


async def test_observe_replays_channel_of_finished_task() -> None:
    registry = TaskRegistry()
    await registry.publish("done-task", _event("done-task", "task_started"))
    await registry.publish(
        "done-task",
        {
            "task_id": "done-task",
            "event": "task_completed",
            "status": "completed",
            "result": {"status": "completed", "final_answer": "正文"},
        },
    )
    await registry.close("done-task")

    app = create_app()
    app.dependency_overrides[get_task_registry] = lambda: registry

    code, body = await _observe(app, "/api/tasks/done-task/stream")
    assert code == 200
    events = _parse_sse(body)
    assert [event["event"] for event in events] == ["task_started", "task_completed"]
    assert events[-1]["result"]["final_answer"] == "正文"


async def test_observe_unknown_task_returns_404() -> None:
    app = create_app()
    app.dependency_overrides[get_task_registry] = TaskRegistry

    code, _ = await _observe(app, "/api/tasks/missing/stream")
    assert code == 404


async def test_observe_synthesizes_terminal_event_from_database(tmp_path: Path) -> None:
    """通道已淘汰（例如后端重启）时，用落库结果合成终态事件。"""
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    repository = TaskRepository(database)
    await repository.start_run(task_id="old", user_id="local-user", query="写综述")
    await repository.finish_run(
        task_id="old", result={"status": "completed", "final_answer": "落库正文"}
    )

    app = create_app()
    app.dependency_overrides[get_task_registry] = TaskRegistry
    app.dependency_overrides[get_task_repository] = lambda: repository

    code, body = await _observe(app, "/api/tasks/old/stream")
    assert code == 200
    events = _parse_sse(body)
    assert len(events) == 1
    assert events[0]["event"] == "task_completed"
    assert events[0]["result"]["final_answer"] == "落库正文"


async def test_observe_synthesizes_cancelled_event_from_database(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    repository = TaskRepository(database)
    await repository.start_run(task_id="gone", user_id="local-user", query="写综述")
    await repository.cancel_run(task_id="gone")

    app = create_app()
    app.dependency_overrides[get_task_registry] = TaskRegistry
    app.dependency_overrides[get_task_repository] = lambda: repository

    code, body = await _observe(app, "/api/tasks/gone/stream")
    assert code == 200
    events = _parse_sse(body)
    assert [event["event"] for event in events] == ["task_cancelled"]
    assert events[0]["status"] == "cancelled"


# --- 关键回归：断开订阅不影响执行 ---
#
# 注意：httpx 的 ASGITransport 会把整个响应体收完才返回，无法模拟「读到一半
# 就断开」。这里用 ``TestClient``（真正逐帧读取）来验证断线与取消。


def test_disconnect_does_not_cancel_background_task() -> None:
    registry = TaskRegistry()
    service = FakeStreamService(steps=20, delay=0.05)
    app = create_app()
    app.dependency_overrides[get_task_registry] = lambda: registry
    app.dependency_overrides[get_task_service] = lambda: service

    with TestClient(app) as client:
        payload = {"query": "写一篇 RAG 综述"}
        with client.stream("POST", "/api/tasks/stream", json=payload) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            first = next(lines)
            task_id = json.loads(first[len("data: ") :])["task_id"]
        # 退出上下文 = 浏览器断开（刷新页面）

        channel = registry.channel(task_id)
        assert channel is not None
        assert channel.closed is False  # 断开订阅没有把任务一起取消

        # 刷新后重新订阅：回放 + 跟随到终态
        body = client.get(f"/api/tasks/{task_id}/stream").text

    events = _parse_sse(body)
    assert events[0]["event"] == "task_started"
    assert events[-1]["event"] == "task_completed"
    assert registry.is_running(task_id) is False


def test_driver_emits_terminal_event_on_unexpected_error() -> None:
    registry = TaskRegistry()
    app = create_app()
    app.dependency_overrides[get_task_registry] = lambda: registry
    app.dependency_overrides[get_task_service] = lambda: FailingStreamService()

    with TestClient(app) as client:
        body = client.post("/api/tasks/stream", json={"query": "q"}).text

    events = _parse_sse(body)
    assert events[0]["event"] == "task_started"
    assert events[-1]["event"] == "task_failed"
    assert events[-1]["error_type"] == "internal_error"


def test_driver_emits_task_cancelled_on_cancel() -> None:
    registry = TaskRegistry()
    service = FakeStreamService(steps=50, delay=0.05)
    app = create_app()
    app.dependency_overrides[get_task_registry] = lambda: registry
    app.dependency_overrides[get_task_service] = lambda: service

    with TestClient(app) as client:
        with client.stream("POST", "/api/tasks/stream", json={"query": "q"}) as response:
            lines = response.iter_lines()
            first = next(lines)
            task_id = json.loads(first[len("data: ") :])["task_id"]

            assert client.post(f"/api/tasks/{task_id}/cancel").status_code == 200
            rest = list(lines)

    events = _parse_sse("\n".join([first, *rest]))
    assert events[-1]["event"] == "task_cancelled"
    assert registry.is_running(task_id) is False
    assert service.finished.is_set() is False  # 执行确实被中断，而不是跑完


# --- 列表：运行中筛选与阶段信息 ---


async def test_list_tasks_filters_running_and_exposes_stage(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    repository = TaskRepository(database)
    await repository.start_run(task_id="busy", user_id="local-user", query="写综述")
    await repository.start_run(task_id="old", user_id="local-user", query="旧任务")
    await repository.finish_run(task_id="old", result={"status": "completed"})

    registry = TaskRegistry()
    await registry.publish(
        "busy",
        _event("busy", "writer_started", step="chapter_2", message="正在撰写第 2 章"),
    )

    app = create_app()
    app.dependency_overrides[get_task_registry] = lambda: registry
    app.dependency_overrides[get_task_repository] = lambda: repository

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        running = await client.get("/api/tasks?status=running")
        everything = await client.get("/api/tasks")

    assert running.status_code == 200
    tasks = running.json()["tasks"]
    assert [task["task_id"] for task in tasks] == ["busy"]
    assert tasks[0]["stage"] == "writer_started"
    assert tasks[0]["message"] == "正在撰写第 2 章"

    # 非运行中任务不带阶段信息；筛选参数不影响默认列表
    listed = {task["task_id"]: task for task in everything.json()["tasks"]}
    assert set(listed) == {"busy", "old"}
    assert listed["old"]["stage"] is None
    assert listed["old"]["message"] is None
