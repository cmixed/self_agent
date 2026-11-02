"""原文输出（系统技能 / 直接入口）的确定性行为测试。

这里覆盖的是「选文档 → 读原文 → 占位符注入」这条链路，全部使用假 Provider
与假文档服务，不依赖真实 DeepSeek / Chroma（AGENTS.md §22）。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fakes import ScriptedProvider
from fastapi.testclient import TestClient

from app.agents.planner import PlanStepModel, _validate_skill_steps
from app.agents.skills import MAX_VERBATIM_STEPS, _run_verbatim_skill
from app.agents.summarizer import inject_verbatim
from app.api.deps import (
    build_memory_repository,
    get_memory_service,
    get_task_repository,
    get_task_service,
)
from app.main import create_app
from app.memory.repository import TaskRecord
from app.models.schemas import DocumentInfo
from app.models.state import initial_state
from app.services.memory_service import MemoryService
from app.services.task_service import TaskService
from app.services.verbatim_service import (
    VerbatimDocumentNotFoundError,
    VerbatimDocumentTooLargeError,
    VerbatimNoDocumentError,
    VerbatimService,
    VerbatimUnavailableError,
    render_verbatim_notice,
)
from app.skills.system import SYSTEM_VERBATIM_SKILL_ID, system_verbatim_entry

ORIGINAL_TEXT = "# RAG 论文\n\n这是知识库中的完整原文。\n\n第二段：逐字输出不得改写。"


class FakeDocumentService:
    """只有原文读取能力的假文档服务。"""

    def __init__(self, documents: dict[str, tuple[str, str, str]]) -> None:
        # document_id -> (filename, title, text)
        self._documents = documents

    async def list_documents(self) -> list[DocumentInfo]:
        return [
            DocumentInfo(
                document_id=document_id,
                filename=filename,
                title=title,
                chunks=1,
            )
            for document_id, (filename, title, _) in self._documents.items()
        ]

    async def read_document_text(self, document_id: str) -> tuple[str, str, str] | None:
        return self._documents.get(document_id)


class FakeRagTool:
    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self._hits = hits
        self.calls: list[dict[str, Any]] = []

    async def search(
        self, query: str, *, top_k: int = 4, document_ids: Any = None
    ) -> list[dict[str, Any]]:
        self.calls.append({"query": query, "top_k": top_k, "document_ids": document_ids})
        return list(self._hits)


def _hit(document_id: str, filename: str, content: str = "片段", score: float = 0.9) -> dict:
    return {
        "document_id": document_id,
        "filename": filename,
        "page": 1,
        "chunk_id": f"{document_id}-0",
        "content": content,
        "score": score,
    }


def _service(
    response_json: str | None = None,
    *,
    documents: dict[str, tuple[str, str, str]] | None = None,
    hits: list[dict[str, Any]] | None = None,
    max_chars: int = 200_000,
) -> VerbatimService:
    docs = documents or {"doc-1": ("rag.md", "RAG 论文", ORIGINAL_TEXT)}
    provider = ScriptedProvider([response_json] if response_json is not None else [])
    tool = FakeRagTool(hits if hits is not None else [_hit("doc-1", "rag.md")])
    return VerbatimService(
        llm=provider,
        document_service_provider=lambda: FakeDocumentService(docs),
        rag_tool_provider=lambda: tool,  # type: ignore[arg-type,return-value]
        max_chars=max_chars,
    )


async def test_explicit_filename_in_query_wins() -> None:
    service = _service()
    output = await service.resolve_direct("请把 rag.md 的原文完整输出")

    assert output["document_id"] == "doc-1"
    assert output["selection"] == "filename"
    assert output["content"] == ORIGINAL_TEXT
    assert output["chars"] == len(ORIGINAL_TEXT)


async def test_single_document_needs_no_llm() -> None:
    service = _service()
    output = await service.resolve_direct("输出这个文档的原文", document_id=None)
    assert output["selection"] == "single"


async def test_explicit_document_id_reads_without_retrieval() -> None:
    service = _service()
    output = await service.resolve_direct("随便", document_id="doc-1")
    assert output["selection"] == "explicit"
    assert output["content"] == ORIGINAL_TEXT


async def test_retrieval_candidates_use_llm_choice() -> None:
    docs = {
        "doc-1": ("a.md", "第一篇", "A 原文"),
        "doc-2": ("b.md", "第二篇", "B 原文"),
    }
    choice = json.dumps({"document_id": "doc-2", "confidence": 0.9, "reason": "主题一致"})
    hits = [_hit("doc-1", "a.md", score=0.8), _hit("doc-2", "b.md", score=0.95)]
    service = _service(choice, documents=docs, hits=hits)

    output = await service.resolve_direct("比较两篇文档")

    assert output["document_id"] == "doc-2"
    assert output["selection"] == "llm"
    assert "主题一致" in output["reason"]
    assert output["content"] == "B 原文"


async def test_llm_failure_falls_back_to_retrieval_order() -> None:
    docs = {
        "doc-1": ("a.md", "第一篇", "A 原文"),
        "doc-2": ("b.md", "第二篇", "B 原文"),
    }
    hits = [_hit("doc-1", "a.md", score=0.8), _hit("doc-2", "b.md", score=0.95)]
    service = _service("不是 JSON", documents=docs, hits=hits)

    output = await service.resolve_direct("比较两篇文档")

    assert output["document_id"] == "doc-2"
    assert output["selection"] == "retrieval"


async def test_llm_invalid_document_id_falls_back() -> None:
    docs = {
        "doc-1": ("a.md", "第一篇", "A 原文"),
        "doc-2": ("b.md", "第二篇", "B 原文"),
    }
    choice = json.dumps({"document_id": "doc-x", "confidence": 1, "reason": "乱选"})
    hits = [_hit("doc-1", "a.md", score=0.8), _hit("doc-2", "b.md", score=0.95)]
    service = _service(choice, documents=docs, hits=hits)

    output = await service.resolve_direct("比较两篇文档")

    assert output["selection"] == "retrieval"
    assert output["document_id"] == "doc-2"


async def test_no_candidates_is_conflict() -> None:
    docs = {
        "doc-1": ("a.md", "第一篇", "A 原文"),
        "doc-2": ("b.md", "第二篇", "B 原文"),
    }
    service = _service(documents=docs, hits=[])
    with pytest.raises(VerbatimNoDocumentError):
        await service.resolve_direct("找一篇不存在的文档")


async def test_retrieval_mode_none_is_rejected() -> None:
    service = _service()
    with pytest.raises(VerbatimUnavailableError):
        await service.resolve_direct("输出原文", retrieval_mode="none")


async def test_empty_scope_never_falls_back_to_whole_kb() -> None:
    service = _service()
    with pytest.raises(VerbatimNoDocumentError):
        await service.resolve_direct("输出原文", scope_ids=[])


async def test_document_outside_scope_is_not_found() -> None:
    docs = {
        "doc-1": ("a.md", "第一篇", "A 原文"),
        "doc-2": ("b.md", "第二篇", "B 原文"),
    }
    service = _service(documents=docs)
    with pytest.raises(VerbatimDocumentNotFoundError):
        await service.resolve_direct("输出原文", document_id="doc-1", scope_ids=["doc-2"])


async def test_too_large_document_is_reported() -> None:
    service = _service(max_chars=5)
    with pytest.raises(VerbatimDocumentTooLargeError):
        await service.resolve_direct("输出原文", document_id="doc-1")


def test_writer_notice_exposes_placeholder_but_not_full_text() -> None:
    state = initial_state("输出原文", task_id="t1")
    state["plan"] = {
        "goal": "输出原文",
        "needs_retrieval": True,
        "steps": [
            {
                "id": "verbatim",
                "type": "skill",
                "description": "在参考来源之前原样输出",
                "skill_id": SYSTEM_VERBATIM_SKILL_ID,
            }
        ],
    }
    state["verbatim_outputs"] = [
        {
            "document_id": "doc-1",
            "filename": "rag.md",
            "title": "RAG 论文",
            "content": ORIGINAL_TEXT,
            "chars": len(ORIGINAL_TEXT),
            "selection": "single",
            "reason": "只有一篇",
        }
    ]

    notice = render_verbatim_notice(state)

    assert "[[VERBATIM:1]]" in notice
    assert "在参考来源之前原样输出" in notice
    assert ORIGINAL_TEXT not in notice


def test_inject_verbatim_replaces_placeholder() -> None:
    state = initial_state("输出原文", task_id="t1")
    state["verbatim_outputs"] = [
        {
            "document_id": "doc-1",
            "filename": "rag.md",
            "title": "RAG 论文",
            "content": ORIGINAL_TEXT,
            "chars": len(ORIGINAL_TEXT),
            "selection": "single",
            "reason": "只有一篇",
        }
    ]

    document = "# 结果\n\n[[VERBATIM:1]]\n\n## 参考来源\n\n[1] rag.md"

    merged = inject_verbatim(document, state)

    assert "[[VERBATIM" not in merged
    assert ORIGINAL_TEXT in merged
    # 原文应插在参考来源之前，而不是追加到文档末尾
    assert merged.index(ORIGINAL_TEXT) < merged.index("## 参考来源")


def test_inject_verbatim_appends_when_no_placeholder() -> None:
    state = initial_state("输出原文", task_id="t1")
    state["verbatim_outputs"] = [
        {
            "document_id": "doc-1",
            "filename": "rag.md",
            "title": "RAG 论文",
            "content": ORIGINAL_TEXT,
            "chars": len(ORIGINAL_TEXT),
            "selection": "single",
            "reason": "只有一篇",
        }
    ]

    merged = inject_verbatim("# 结果\n\n## 参考来源\n\n[1] rag.md", state)

    assert "## 原文：《rag.md》" in merged
    assert ORIGINAL_TEXT in merged
    assert merged.index("## 原文：") < merged.index("## 参考来源")


def test_planner_drops_verbatim_when_retrieval_disabled() -> None:
    catalog = [system_verbatim_entry()]
    steps = [
        PlanStepModel(id="write", type="writing", description="写作"),
        PlanStepModel(
            id="verbatim",
            type="skill",
            description="输出原文",
            skill_id=SYSTEM_VERBATIM_SKILL_ID,
        ),
    ]

    kept = _validate_skill_steps(steps, catalog, retrieval_mode="none")  # type: ignore[arg-type]

    assert [step.type for step in kept] == ["writing"]


def test_planner_keeps_at_most_one_verbatim_step() -> None:
    catalog = [system_verbatim_entry()]
    steps = [
        PlanStepModel(
            id=f"verbatim-{index}",
            type="skill",
            description="输出原文",
            skill_id=SYSTEM_VERBATIM_SKILL_ID,
        )
        for index in range(MAX_VERBATIM_STEPS + 1)
    ]

    kept = _validate_skill_steps(steps, catalog)  # type: ignore[arg-type]

    assert len(kept) == MAX_VERBATIM_STEPS


async def test_verbatim_skill_failure_still_advances_step() -> None:
    """读取失败也必须写一条 skill_outputs，否则技能路由会反复执行该步骤。"""

    def failing_provider():
        class Broken:
            async def resolve_for_state(self, state, step):
                raise RuntimeError("读取失败")

        return Broken()

    state = initial_state("输出原文", task_id="t1")
    step = {
        "id": "verbatim",
        "type": "skill",
        "description": "输出原文",
        "skill_id": SYSTEM_VERBATIM_SKILL_ID,
    }

    update = await _run_verbatim_skill(  # type: ignore[arg-type]
        state, step, system_verbatim_entry(), failing_provider
    )

    assert update["skill_outputs"][0]["step_id"] == "verbatim"
    assert update["step_results"][0]["status"] == "error"
    assert "verbatim_outputs" not in update


# --- 生成流程：Planner 选择系统技能后，原文由确定性分支插入 -------------------


def _build_service(documents: dict[str, tuple[str, str, str]] | None = None) -> TaskService:
    docs = documents or {"doc-1": ("rag.md", "RAG 论文", ORIGINAL_TEXT)}
    plan = json.dumps(
        {
            "goal": "输出原文并补充说明",
            "needs_retrieval": True,
            "steps": [
                {"id": "research", "type": "retrieval", "description": "检索资料"},
                {
                    "id": "verbatim",
                    "type": "skill",
                    "description": "原样输出知识库原文",
                    "skill_id": SYSTEM_VERBATIM_SKILL_ID,
                },
                {"id": "write", "type": "writing", "description": "写一段说明"},
            ],
        },
        ensure_ascii=False,
    )
    outline = json.dumps({"sections": [{"title": "原文"}]}, ensure_ascii=False)
    provider = ScriptedProvider(
        [plan, outline],
        default_text="以下是原文：\n\n[[VERBATIM:1]]\n",
    )
    tool = FakeRagTool([_hit("doc-1", "rag.md")])

    return TaskService(
        provider,
        rag_tool_provider=lambda: tool,  # type: ignore[arg-type,return-value]
        skill_catalog=[system_verbatim_entry()],  # type: ignore[list-item]
        verbatim_provider=lambda llm: VerbatimService(
            llm=llm,
            document_service_provider=lambda: FakeDocumentService(docs),
        ),
        max_retries=0,
    )


async def test_generation_inserts_original_text_without_llm_context() -> None:
    service = _build_service()

    state = await service.run("把 rag.md 的原文完整输出", use_skills=False, depth="longform")

    assert state["final_answer"].count(ORIGINAL_TEXT) == 1
    assert "[[VERBATIM" not in state["final_answer"]
    assert len(state["verbatim_outputs"]) == 1
    assert state["verbatim_outputs"][0]["filename"] == "rag.md"
    # 原文不进入 skill_outputs（否则会被注入模型上下文）
    assert all(ORIGINAL_TEXT not in item["content"] for item in state["skill_outputs"])


# --- 直接入口：不进入 Graph，只推送查找 / 读取两步 ---------------------------


def _direct_app(documents: dict[str, tuple[str, str, str]] | None = None):
    docs = documents or {"doc-1": ("rag.md", "RAG 论文", ORIGINAL_TEXT)}
    app = create_app()
    service = TaskService(
        ScriptedProvider([]),
        verbatim_provider=lambda llm: VerbatimService(
            llm=llm,
            document_service_provider=lambda: FakeDocumentService(docs),
        ),
        max_retries=0,
    )
    app.dependency_overrides[get_task_service] = lambda: service
    return app


def test_direct_verbatim_task_endpoint_returns_full_text() -> None:
    app = _direct_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/tasks",
            json={"query": "输出 rag.md 原文", "output_mode": "verbatim"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["output_mode"] == "verbatim"
    assert body["verbatim"]["filename"] == "rag.md"
    assert body["verbatim"]["selection"] == "filename"
    assert ORIGINAL_TEXT in body["final_answer"]


def test_direct_verbatim_stream_only_reports_lookup_and_read() -> None:
    app = _direct_app()

    with (
        TestClient(app) as client,
        client.stream(
            "POST",
            "/api/tasks/stream",
            json={"query": "输出 rag.md 原文", "output_mode": "verbatim"},
        ) as response,
    ):
        assert response.status_code == 200
        body = "".join(response.iter_text())

    frames = [line[len("data: ") :] for line in body.splitlines() if line.startswith("data: ")]
    events = [json.loads(frame) for frame in frames]

    assert [event["event"] for event in events] == [
        "task_started",
        "verbatim_started",
        "verbatim_selected",
        "verbatim_completed",
        "task_completed",
    ]
    assert events[0]["mode"] == "verbatim"
    selected = events[2]
    assert selected["filename"] == "rag.md"
    assert selected["selection"] == "filename"
    assert events[-1]["result"]["output_mode"] == "verbatim"
    assert ORIGINAL_TEXT in events[-1]["result"]["final_answer"]


def test_direct_verbatim_rejects_retrieval_none() -> None:
    app = _direct_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/tasks",
            json={
                "query": "输出 rag.md 原文",
                "output_mode": "verbatim",
                "retrieval_mode": "none",
            },
        )

    assert response.status_code == 409


def test_direct_verbatim_rejects_document_outside_scope() -> None:
    app = _direct_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/tasks",
            json={
                "query": "输出原文",
                "output_mode": "verbatim",
                "verbatim_document_id": "doc-1",
                "retrieval_mode": "selected",
                "scope": {"category_ids": [], "document_ids": ["doc-2"]},
            },
        )

    assert response.status_code == 409


def test_verbatim_task_never_extracts_memory(monkeypatch) -> None:
    """即使 query 里有「记住」，原文输出也不写入长期记忆。"""
    from app.core.config import get_settings

    monkeypatch.setenv("MEMORY_AUTO_EXTRACT", "true")
    get_settings.cache_clear()
    app = _direct_app()
    memory_provider = ScriptedProvider(
        [json.dumps({"preferences": [], "memories": []}, ensure_ascii=False)]
    )
    app.dependency_overrides[get_memory_service] = lambda: MemoryService(
        build_memory_repository(), memory_provider
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/tasks",
            json={"query": "记住：输出 rag.md 原文", "output_mode": "verbatim"},
        )

    assert response.status_code == 200
    assert response.json().get("memory_updates") is None
    assert memory_provider.calls == []


def test_rerun_verbatim_reuses_previous_document() -> None:
    """重跑原文任务时沿用上次选中的文档，而不是重新做一次自动选择。"""
    docs = {
        "doc-1": ("a.md", "第一篇", "A 原文"),
        "doc-2": ("b.md", "第二篇", "B 原文"),
    }
    app = _direct_app(docs)
    service = TaskService(
        ScriptedProvider([]),
        verbatim_provider=lambda llm: VerbatimService(
            llm=llm,
            document_service_provider=lambda: FakeDocumentService(docs),
        ),
        max_retries=0,
    )

    record = TaskRecord(
        task_id="task-old",
        user_id="local-user",
        query="输出原文",
        status="completed",
        created_at="2026-01-01T00:00:00",
        finished_at="2026-01-01T00:00:01",
        error_type=None,
        result={
            "task_id": "task-old",
            "status": "completed",
            "mode": "verbatim",
            "output_mode": "verbatim",
            "retrieval_mode": "all",
            "verbatim": {"document_id": "doc-2", "filename": "b.md"},
        },
    )

    class FakeRepository:
        async def get_task(self, task_id: str):
            return record if task_id == "task-old" else None

        async def fail_run(self, task_id: str, error_type: str) -> None:
            return None

    app.dependency_overrides[get_task_service] = lambda: service
    app.dependency_overrides[get_task_repository] = lambda: FakeRepository()

    with (
        TestClient(app) as client,
        client.stream("POST", "/api/tasks/task-old/rerun") as response,
    ):
        assert response.status_code == 200
        body = "".join(response.iter_text())

    frames = [line[len("data: ") :] for line in body.splitlines() if line.startswith("data: ")]
    events = [json.loads(frame) for frame in frames]

    assert events[0]["rerun_of"] == "task-old"
    result = events[-1]["result"]
    assert result["verbatim"]["document_id"] == "doc-2"
    assert "B 原文" in result["final_answer"]
