"""「继续生成」（断点续跑）与「重新生成」的测试。

关键回归：续跑必须从失败的那个节点重新开始，**不重做已完成章节**。
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
import pytest
from fakes import ScriptedProvider

from app.core.checkpoint import CheckpointStore
from app.llm.base import LLMError
from app.memory.repository import TaskRepository
from app.memory.sqlite import SqliteDatabase
from app.services.task_service import TaskNotResumableError, TaskService

PLAN = json.dumps(
    {
        "goal": "写综述",
        "needs_retrieval": False,
        "steps": [{"id": "w", "type": "writing", "description": "撰写"}],
    },
    ensure_ascii=False,
)
OUTLINE_3 = json.dumps(
    {"sections": [{"title": "第一章"}, {"title": "第二章"}, {"title": "第三章"}]},
    ensure_ascii=False,
)
PASS = json.dumps(
    {"passed": True, "issues": [], "suggested_action": "continue"}, ensure_ascii=False
)


class FailingProvider(ScriptedProvider):
    """在第 fail_after 次调用后抛错，模拟额度不足 / 密钥失效导致的中断。"""

    def __init__(self, responses: list[str], *, fail_after: int) -> None:
        super().__init__(responses)
        self._fail_after = fail_after

    async def chat(self, messages, *, temperature=0.7, max_tokens=None, json_mode=False):
        if len(self.calls) >= self._fail_after:
            raise LLMError("模拟额度不足，任务中断")
        return await super().chat(
            messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
        )


async def _checkpointer(tmp_path: Path) -> tuple[CheckpointStore, aiosqlite.Connection]:
    store = CheckpointStore(tmp_path / "checkpoints.db")
    await store.start()
    assert store.saver is not None
    return store, store._connection  # type: ignore[attr-defined]


async def test_resume_continues_without_redoing_finished_chapters(tmp_path) -> None:
    store, conn = await _checkpointer(tmp_path)
    saver = store.saver
    task_id = "task-resume"
    config_input_query = "写综述"

    # 第 1 次：写到第 2 章时中断（plan/outline/第1章 之后；章级校验不发 LLM）
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    failing = FailingProvider([PLAN, OUTLINE_3], fail_after=3)
    service1 = TaskService(
        failing,
        checkpointer=saver,
        repository=TaskRepository(database),
        max_retries=0,
    )
    events1 = [event async for event in service1.stream(config_input_query, task_id=task_id)]
    assert events1[-1]["event"] == "task_failed"

    # 断点里应已写完第 1 章
    snapshot = await service1.snapshot(task_id)
    assert snapshot is not None
    written = [s["title"] for s in snapshot["sections"] if s.get("content")]
    assert written == ["第一章"]

    # 第 2 次：续跑（同 task_id）
    resuming = ScriptedProvider([])
    service2 = TaskService(
        resuming,
        checkpointer=saver,
        repository=TaskRepository(database),
        max_retries=0,
    )
    events2 = [event async for event in service2.resume(task_id, user_id="local-user")]

    names = [event["event"] for event in events2]
    assert names[0] == "task_resumed"
    resumed_event = events2[0]
    assert resumed_event["resumed"] is True
    assert resumed_event["chapters_written"] == 1
    assert resumed_event["outline"] == ["第一章", "第二章", "第三章"]
    assert names[-1] == "task_completed"

    # 决定性断言：续跑只写了第 2、3 章，没有重写第 1 章
    prompts = "\n".join(call[1].content for call in resuming.calls)
    assert "第 2/3 章" in prompts
    assert "第 3/3 章" in prompts
    assert "第 1/3 章" not in prompts

    final = events2[-1]["result"]
    assert final["status"] == "completed"
    assert len(final["final_answer"]) > 0
    await conn.close()


async def test_resume_without_checkpoint_raises(tmp_path) -> None:
    store, conn = await _checkpointer(tmp_path)
    service = TaskService(ScriptedProvider([]), checkpointer=store.saver, max_retries=0)

    with pytest.raises(TaskNotResumableError):
        _ = [event async for event in service.resume("no-such-task")]
    await conn.close()


async def test_resume_appends_attempt_and_keeps_previous_failure(tmp_path) -> None:
    """续跑追加「第 2 次尝试」，第 1 次的失败原因必须保留。"""
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    repository = TaskRepository(database)
    store, conn = await _checkpointer(tmp_path)

    task_id = "task-attempts"
    failing = FailingProvider([PLAN, OUTLINE_3], fail_after=1)
    service = TaskService(failing, checkpointer=store.saver, repository=repository, max_retries=0)
    _ = [event async for event in service.stream("写综述", task_id=task_id)]

    attempts = await repository.list_attempts(task_id)
    assert [(a.attempt_no, a.status, a.error_type) for a in attempts] == [
        (1, "failed", "llm_error")
    ]

    # 续跑 = 追加第 2 次尝试（不覆盖第 1 次）
    await repository.resume_run(task_id=task_id)
    attempts = await repository.list_attempts(task_id)
    assert [(a.attempt_no, a.status) for a in attempts] == [(1, "failed"), (2, "running")]
    assert attempts[0].error_type == "llm_error"
    assert attempts[0].finished_at is not None

    # 第 2 次完成后，历史里两条记录都在
    await repository.finish_run(
        task_id=task_id,
        result={"status": "completed", "retry_count": 0, "failed_chapters": []},
    )
    attempts = await repository.list_attempts(task_id)
    assert [(a.attempt_no, a.status) for a in attempts] == [(1, "failed"), (2, "completed")]
    record = await repository.get_task(task_id)
    assert record is not None and record.status == "completed"
    await conn.close()


# --- API 层（全部走 HTTP，避免同一 checkpointer 跨事件循环使用）---


def _parse_sse(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


def _failing_service(fail_after: int = 3) -> TaskService:
    from app.api.deps import build_checkpoint_store, build_task_repository

    return TaskService(
        FailingProvider([PLAN, OUTLINE_3], fail_after=fail_after),
        checkpointer=build_checkpoint_store().saver,
        repository=build_task_repository(),
        max_retries=0,
    )


def _working_service(provider: ScriptedProvider) -> TaskService:
    from app.api.deps import build_checkpoint_store, build_task_repository

    return TaskService(
        provider,
        checkpointer=build_checkpoint_store().saver,
        repository=build_task_repository(),
        max_retries=0,
    )


def _start_failing_task(client, app, *, fail_after: int = 3) -> str:
    """通过 HTTP 跑一次会中断的任务，返回 task_id（留下 failed 记录 + 断点）。"""
    from app.api.deps import get_task_service

    app.dependency_overrides[get_task_service] = lambda: _failing_service(fail_after)
    response = client.post("/api/tasks/stream", json={"query": "写综述"})
    events = _parse_sse(response.text)
    assert events[-1]["event"] == "task_failed"
    return events[0]["task_id"]


def test_detail_exposes_resumable_and_endpoint_resumes() -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_task_service
    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        task_id = _start_failing_task(client, app)

        detail = client.get(f"/api/tasks/{task_id}").json()
        assert detail["status"] == "failed"
        assert detail["running"] is False
        assert detail["resumable"] is True

        resuming = ScriptedProvider([])
        app.dependency_overrides[get_task_service] = lambda: _working_service(resuming)

        response = client.post(f"/api/tasks/{task_id}/resume")
        assert response.status_code == 200
        events = _parse_sse(response.text)
        assert events[0]["event"] == "task_resumed"
        assert events[0]["chapters_written"] == 1
        assert events[-1]["event"] == "task_completed"
        assert events[-1]["result"]["status"] == "completed"

        # 决定性断言：只写了第 2、3 章
        prompts = "\n".join(call[1].content for call in resuming.calls)
        assert "第 2/3 章" in prompts
        assert "第 1/3 章" not in prompts


async def test_resume_endpoint_rejects_when_not_resumable() -> None:
    """任务记录存在但没有任何检查点（例如 Checkpoint 未启用或历史记录）→ 409。"""
    from fastapi.testclient import TestClient

    from app.api.deps import build_task_repository
    from app.main import create_app

    with TestClient(create_app()) as client:
        repository = build_task_repository()
        await repository.start_run(task_id="task-no-cp", user_id="local-user", query="写综述")
        await repository.fail_run(task_id="task-no-cp", error_type="llm_error")

        detail = client.get("/api/tasks/task-no-cp").json()
        assert detail["status"] == "failed"
        assert detail["resumable"] is False

        resumed = client.post("/api/tasks/task-no-cp/resume")
        assert resumed.status_code == 409
        assert "重新生成" in resumed.json()["detail"]


def test_failure_at_first_node_is_resumable() -> None:
    """第一个节点就失败（如密钥失效）同样可续跑：检查点保留了初始状态。"""
    from fastapi.testclient import TestClient

    from app.api.deps import get_task_service
    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        task_id = _start_failing_task(client, app, fail_after=0)

        detail = client.get(f"/api/tasks/{task_id}").json()
        assert detail["resumable"] is True

        resuming = ScriptedProvider([PLAN, OUTLINE_3])
        app.dependency_overrides[get_task_service] = lambda: _working_service(resuming)

        response = client.post(f"/api/tasks/{task_id}/resume")
        events = _parse_sse(response.text)
        assert events[-1]["event"] == "task_completed"
        # 从最初开始重跑：planner 会再次被调用
        planner_prompts = [call[0].content for call in resuming.calls]
        assert any("规划器" in prompt or "规划" in prompt for prompt in planner_prompts)


def test_rerun_creates_new_task_and_keeps_original() -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_task_service
    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        task_id = _start_failing_task(client, app)

        provider = ScriptedProvider([PLAN, OUTLINE_3])
        app.dependency_overrides[get_task_service] = lambda: _working_service(provider)

        response = client.post(f"/api/tasks/{task_id}/rerun")
        assert response.status_code == 200
        events = _parse_sse(response.text)
        assert events[0]["event"] == "task_started"
        assert events[0]["rerun_of"] == task_id
        assert events[0]["task_id"] != task_id  # 新任务 id
        assert events[-1]["event"] == "task_completed"

        # 原任务记录保持不变，新任务有自己的记录
        assert client.get(f"/api/tasks/{task_id}").json()["status"] == "failed"
        new_detail = client.get(f"/api/tasks/{events[0]['task_id']}").json()
        assert new_detail["query"] == "写综述"
