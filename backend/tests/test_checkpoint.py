from __future__ import annotations

from pathlib import Path

import pytest
from fakes import OUTLINE_JSON, PLAN_JSON, ScriptedProvider
from fastapi.testclient import TestClient

from app.api.deps import (
    build_memory_repository,
    build_task_repository,
    get_checkpoint_store,
    get_checkpointer,
    get_memory_service,
    get_task_service,
)
from app.core.agent_graph import build_graph
from app.core.checkpoint import CheckpointStore
from app.main import create_app
from app.models.state import initial_state
from app.services.memory_service import MemoryService
from app.services.task_service import TaskService


async def test_checkpoint_store_setup_and_close(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "nested" / "checkpoints.db")
    await store.start()
    try:
        assert store.path.exists()
        assert store.saver is not None
    finally:
        await store.close()

    assert store.saver is None


async def test_graph_writes_checkpoints_per_thread(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "checkpoints.db")
    await store.start()
    try:
        provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON])
        graph = build_graph(provider, checkpointer=store.saver, max_retries=0)

        await graph.ainvoke(
            initial_state("写一篇 RAG 综述", task_id="t-cp"),
            config={"configurable": {"thread_id": "t-cp"}},
        )

        assert store.saver is not None
        found = await store.saver.aget_tuple({"configurable": {"thread_id": "t-cp"}})
        assert found is not None
        values = found.checkpoint["channel_values"]
        assert values["task_status"] == "completed"
        assert len(values["sections"]) == 2

        # 不同线程互不影响
        assert await store.saver.aget_tuple({"configurable": {"thread_id": "other"}}) is None
    finally:
        await store.close()


def _client(provider: ScriptedProvider) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: TaskService(
        provider,
        repository=build_task_repository(),
        checkpointer=get_checkpointer(),
        max_retries=0,
    )
    # 长期记忆提取保持离线
    app.dependency_overrides[get_memory_service] = lambda: MemoryService(
        build_memory_repository(), None
    )
    return TestClient(app)


def test_task_state_endpoint_returns_structured_summary() -> None:
    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON])
    with _client(provider) as client:
        created = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})
        assert created.status_code == 200
        task_id = created.json()["task_id"]

        state = client.get(f"/api/tasks/{task_id}/state")

    assert state.status_code == 200
    body = state.json()
    assert body["task_id"] == task_id
    assert body["status"] == "completed"
    assert body["is_complete"] is True
    assert body["current_step"] == "summarize"
    assert body["chapters_written"] == 2
    assert body["outline"] == ["引言", "chunk 大小的影响"]
    assert body["checkpoint_id"]
    # 不暴露消息原文 / 推理过程
    assert "messages" not in body


def test_task_state_unknown_task_returns_404() -> None:
    with _client(ScriptedProvider([PLAN_JSON, OUTLINE_JSON])) as client:
        response = client.get("/api/tasks/no-such-task/state")
    assert response.status_code == 404


def test_task_state_returns_503_when_checkpoint_disabled() -> None:
    app = create_app()
    app.dependency_overrides[get_checkpoint_store] = lambda: None
    app.dependency_overrides[get_task_service] = lambda: TaskService(
        ScriptedProvider([PLAN_JSON, OUTLINE_JSON]), max_retries=0
    )
    with TestClient(app) as client:
        response = client.get("/api/tasks/anything/state")
    assert response.status_code == 503
    assert response.json()["detail"] == "Checkpoint 未启用"


@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("false", False), ("0", False)])
def test_checkpoint_enabled_flag_is_parsed(raw: str, expected: bool, monkeypatch) -> None:
    monkeypatch.setenv("CHECKPOINT_ENABLED", raw)
    from app.core.config import Settings

    assert Settings(_env_file=None).checkpoint_enabled is expected
