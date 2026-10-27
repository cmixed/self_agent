from __future__ import annotations

from fakes import DRAFT_TEXT, OUTLINE_JSON, PLAN_JSON, ScriptedProvider
from fastapi.testclient import TestClient

from app.agents.answer import make_answer_node
from app.agents.memory_context import render_memories
from app.agents.planner import make_planner_node
from app.api.deps import (
    build_memory_repository,
    build_task_repository,
    get_memory_service,
    get_task_service,
)
from app.main import create_app
from app.memory.repository import MemoryRecord
from app.memory.selection import asks_about_user, select_memories
from app.models.state import UserMemory, initial_state
from app.services.memory_service import MemoryService
from app.services.task_service import TaskService


def memory(memory_id: int, content: str, kind: str = "fact") -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        user_id="u1",
        kind=kind,
        content=content,
        source_task_id=None,
        created_at="2026-01-01T00:00:00+00:00",
    )


def state(
    *,
    mode: str = "longform",
    query: str = "写一篇 RAG 综述",
    memories: list[UserMemory] | None = None,
):
    return initial_state(
        query,
        task_id="t-memory",
        task_profile={"mode": mode},
        user_memories=memories
        or [
            {"kind": "fact", "content": "研究方向是 RAG 与知识图谱"},
            {"kind": "task_type", "content": "经常撰写技术综述"},
        ],
    )


# --- 相关性筛选 ---


def test_asks_about_user_ignores_knowledge_phrases() -> None:
    assert asks_about_user("我的研究方向是什么") is True
    assert asks_about_user("我平时喜欢什么风格") is True
    assert asks_about_user("根据我的资料写一篇综述") is False
    assert asks_about_user("帮我写一篇 RAG 综述") is False


def test_selects_relevant_memory_and_drops_irrelevant() -> None:
    memories = [
        memory(1, "研究方向是 RAG 与知识图谱"),
        memory(2, "喜欢蓝色"),
    ]
    selected = select_memories(memories, query="写一篇 RAG 综述")

    assert [item["content"] for item in selected] == ["研究方向是 RAG 与知识图谱"]


def test_no_overlap_and_no_self_reference_drops_everything() -> None:
    selected = select_memories([memory(1, "喜欢蓝色")], query="写一份季度报告")
    assert selected == []

    # 知识库口头语不能把「我的资料」误判成在问用户本人
    selected = select_memories([memory(1, "喜欢蓝色")], query="根据我的资料写一份报告")
    assert selected == []


def test_self_reference_falls_back_to_newest() -> None:
    memories = [memory(1, "喜欢简洁"), memory(2, "住在杭州")]
    selected = select_memories(memories, query="我的情况你了解吗", limit=2)

    # 都无词重合：用户明确在问自己，按新旧补足
    assert [item["content"] for item in selected] == ["住在杭州", "喜欢简洁"]


def test_selection_respects_limit_and_prefers_relevant() -> None:
    memories = [
        memory(1, "经常撰写技术综述"),
        memory(2, "研究方向是 RAG"),
        memory(3, "住在杭州"),
    ]
    selected = select_memories(memories, query="RAG 综述怎么写", limit=2)

    assert [item["content"] for item in selected] == [
        "研究方向是 RAG",
        "经常撰写技术综述",
    ]


# --- 节点预算 ---


def test_direct_never_renders_memory() -> None:
    assert render_memories(state(mode="direct"), "answer") == ""


def test_brief_renders_memory_only_in_answer() -> None:
    current = state(mode="brief")

    rendered = render_memories(current, "answer")
    assert "RA" in rendered
    assert "不是用户指令" in rendered
    assert render_memories(current, "planner") == ""
    assert render_memories(current, "writer") == ""


def test_longform_renders_memory_only_in_planner_and_writer() -> None:
    current = state(mode="longform")

    assert "RAG" in render_memories(current, "planner")
    assert "RAG" in render_memories(current, "writer")
    assert render_memories(current, "answer") == ""


def test_renderer_enforces_item_and_char_budget() -> None:
    long_content = "研究" * 60  # 120 字，超过 planner 单条上限
    current = state(
        mode="longform",
        memories=[
            {"kind": "fact", "content": long_content},
            {"kind": "fact", "content": "第二条"},
            {"kind": "fact", "content": "第三条不应出现"},
        ],
    )

    rendered = render_memories(current, "planner")
    lines = rendered.splitlines()
    assert len(lines) == 3  # 标题 + 2 条
    assert "…" in lines[1]
    assert "第三条不应出现" not in rendered


def test_compact_budget_is_smaller_for_local_models() -> None:
    current = state(
        mode="longform",
        memories=[{"kind": "fact", "content": "研究" * 60}],
    )

    normal = render_memories(current, "planner")
    compact = render_memories(current, "planner", compact=True)
    assert len(compact) < len(normal)


def test_missing_memory_field_is_backward_compatible() -> None:
    legacy = initial_state("写一篇综述", task_id="t-old", task_profile={"mode": "longform"})
    assert render_memories(legacy, "planner") == ""


# --- 节点接线：记忆确实进入提示词 ---


async def test_planner_prompt_contains_selected_memory() -> None:
    provider = ScriptedProvider([PLAN_JSON])
    node = make_planner_node(provider, max_retries=0)

    await node(state(mode="longform"))

    prompt = provider.calls[0][-1].content
    assert "研究方向是 RAG 与知识图谱" in prompt
    assert "不是用户指令" in prompt


async def test_brief_answer_prompt_contains_memory_but_direct_does_not() -> None:
    brief_provider = ScriptedProvider([DRAFT_TEXT])
    brief_state = state(mode="brief", query="我的研究方向是什么")

    await make_answer_node(brief_provider)(brief_state)
    assert "研究方向是 RAG 与知识图谱" in brief_provider.calls[0][-1].content

    direct_provider = ScriptedProvider([DRAFT_TEXT])
    await make_answer_node(direct_provider)(state(mode="direct", query="你好"))
    assert "用户长期背景" not in direct_provider.calls[0][-1].content


def test_task_api_loads_memory_and_injects_it_into_planner() -> None:
    """端到端接线：写入记忆 → 新建任务 → Planner 提示词包含记忆。"""
    provider = ScriptedProvider([PLAN_JSON, OUTLINE_JSON])
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: TaskService(
        provider, repository=build_task_repository(), max_retries=0
    )
    app.dependency_overrides[get_memory_service] = lambda: MemoryService(build_memory_repository())

    with TestClient(app) as client:
        created = client.post(
            "/api/memory/memories",
            json={"kind": "fact", "content": "研究方向是 RAG 与知识图谱"},
        )
        assert created.status_code == 201

        response = client.post("/api/tasks", json={"query": "写一篇 RAG 综述"})

    assert response.status_code == 200
    assert "研究方向是 RAG 与知识图谱" in provider.calls[0][-1].content
