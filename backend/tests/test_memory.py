from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import ScriptedProvider
from fastapi.testclient import TestClient

from app.llm.base import LLMError, LLMProvider, LLMResponse
from app.main import create_app
from app.memory.repository import MemoryRepository
from app.memory.sqlite import SqliteDatabase
from app.services.memory_service import MemoryService

EXTRACTION_JSON = json.dumps(
    {
        "preferences": [{"key": "style", "value": "偏好学术严谨"}],
        "memories": [
            {"kind": "task_type", "content": "经常撰写技术综述"},
            {"kind": "preference", "content": "希望输出 Markdown"},
        ],
    },
    ensure_ascii=False,
)


@pytest.fixture
def repository(tmp_path: Path) -> MemoryRepository:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    return MemoryRepository(database)


# --- 仓储 ---


async def test_preferences_crud(repository: MemoryRepository) -> None:
    assert await repository.get_preferences("u1") == {}

    await repository.set_preference("u1", "style", "简洁")
    await repository.set_preference("u1", "language", "中文")
    assert await repository.get_preferences("u1") == {"language": "中文", "style": "简洁"}

    # 同键覆盖
    await repository.set_preference("u1", "style", "严谨")
    assert (await repository.get_preferences("u1"))["style"] == "严谨"

    assert await repository.delete_preference("u1", "style") is True
    assert await repository.delete_preference("u1", "style") is False
    assert await repository.get_preferences("u1") == {"language": "中文"}


async def test_memories_are_deduplicated(repository: MemoryRepository) -> None:
    first = await repository.add_memory("u1", kind="fact", content="使用 LangGraph")
    assert first is not None
    assert first.memory_id > 0

    duplicate = await repository.add_memory("u1", kind="fact", content="使用 LangGraph")
    assert duplicate is None
    assert len(await repository.list_memories("u1")) == 1


async def test_memory_list_and_delete(repository: MemoryRepository) -> None:
    first = await repository.add_memory("u1", kind="fact", content="a")
    second = await repository.add_memory("u1", kind="fact", content="b")
    assert first is not None and second is not None

    # 最新在前
    assert [m.content for m in await repository.list_memories("u1")] == ["b", "a"]

    assert await repository.delete_memory("u1", first.memory_id) is True
    assert await repository.delete_memory("u1", first.memory_id) is False
    assert [m.content for m in await repository.list_memories("u1")] == ["b"]


async def test_long_term_memory_is_per_user(repository: MemoryRepository) -> None:
    await repository.set_preference("alice", "style", "严谨")
    await repository.set_preference("bob", "style", "轻松")
    await repository.add_memory("alice", kind="fact", content="alice-only")

    assert await repository.get_preferences("alice") == {"style": "严谨"}
    assert await repository.get_preferences("bob") == {"style": "轻松"}
    assert await repository.list_memories("bob") == []

    # 他人无法删除
    memories = await repository.list_memories("alice")
    assert await repository.delete_memory("bob", memories[0].memory_id) is False


# --- 服务：自动提取 ---


class _FailingProvider(LLMProvider):
    name = "failing"

    async def chat(self, messages, **kwargs) -> LLMResponse:
        raise LLMError("模拟失败")

    async def aclose(self) -> None:
        return None


async def test_extract_stores_preferences_and_memories(repository: MemoryRepository) -> None:
    service = MemoryService(repository, ScriptedProvider([EXTRACTION_JSON]))

    extracted = await service.extract_from_task(
        "u1", query="写一篇综述", result={"final_answer": "正文"}, task_id="t1"
    )

    assert extracted is not None
    assert extracted["attempted"] is True
    assert extracted["trigger"] == "manual"
    assert extracted["preferences"] == [{"key": "style", "value": "偏好学术严谨"}]
    assert extracted["memories"] == [
        {"kind": "task_type", "content": "经常撰写技术综述"},
        {"kind": "fact", "content": "希望输出 Markdown"},
    ]
    assert extracted["skipped"] == 0
    assert await repository.get_preferences("u1") == {"style": "偏好学术严谨"}
    contents = [m.content for m in await repository.list_memories("u1")]
    assert contents == ["希望输出 Markdown", "经常撰写技术综述"]
    assert all(m.source_task_id == "t1" for m in await repository.list_memories("u1"))


async def test_extract_is_noop_without_llm(repository: MemoryRepository) -> None:
    service = MemoryService(repository, None)

    assert await service.extract_from_task("u1", query="q", result={"final_answer": "a"}) is None
    assert await repository.get_preferences("u1") == {}


async def test_extract_is_noop_for_empty_query(repository: MemoryRepository) -> None:
    service = MemoryService(repository, ScriptedProvider([EXTRACTION_JSON]))

    assert await service.extract_from_task("u1", query="  ", result={}) is None
    assert await repository.get_preferences("u1") == {}


async def test_extract_tolerates_llm_failure(repository: MemoryRepository) -> None:
    service = MemoryService(repository, _FailingProvider())

    assert await service.extract_from_task("u1", query="q", result={"final_answer": "a"}) is None
    assert await repository.get_preferences("u1") == {}


async def test_extract_does_not_overwrite_existing_preferences(
    repository: MemoryRepository,
) -> None:
    """显式设置的偏好优先，自动提取不得覆盖。"""
    await repository.set_preference("u1", "style", "用户自己设定的风格")
    payload = json.dumps(
        {
            "preferences": [
                {"key": "style", "value": "模型推断的风格"},
                {"key": "language", "value": "使用中文"},
            ],
            "memories": [],
        },
        ensure_ascii=False,
    )
    service = MemoryService(repository, ScriptedProvider([payload]))

    await service.extract_from_task("u1", query="写一篇综述", result={"final_answer": "正文"})

    preferences = await repository.get_preferences("u1")
    assert preferences["style"] == "用户自己设定的风格"
    # 新键仍会被写入
    assert preferences["language"] == "使用中文"


async def test_extract_tolerates_invalid_json(repository: MemoryRepository) -> None:
    service = MemoryService(repository, ScriptedProvider(["不是 JSON"], default="也不是"))

    assert await service.extract_from_task("u1", query="q", result={"final_answer": "a"}) is None
    assert await repository.get_preferences("u1") == {}


# --- 去重：偏好与记忆的边界 ---


async def test_extract_normalizes_preference_keys(repository: MemoryRepository) -> None:
    payload = json.dumps(
        {
            "preferences": [{"key": "写作风格", "value": "偏好学术严谨"}],
            "memories": [],
        },
        ensure_ascii=False,
    )
    service = MemoryService(repository, ScriptedProvider([payload]))

    await service.extract_from_task("u1", query="写综述", result={"final_answer": "正文"})

    assert await repository.get_preferences("u1") == {"style": "偏好学术严谨"}


async def test_extract_deduplicates_preference_values_under_other_keys(
    repository: MemoryRepository,
) -> None:
    await repository.set_preference("u1", "language", "中文")
    payload = json.dumps(
        {
            "preferences": [
                {"key": "style", "value": "中文"},
                {"key": "format", "value": "Markdown"},
            ],
            "memories": [],
        },
        ensure_ascii=False,
    )
    service = MemoryService(repository, ScriptedProvider([payload]))

    await service.extract_from_task("u1", query="写综述", result={"final_answer": "正文"})

    assert await repository.get_preferences("u1") == {"format": "Markdown", "language": "中文"}


async def test_extract_skips_near_duplicate_memory_across_tasks(
    repository: MemoryRepository,
) -> None:
    first = json.dumps(
        {"preferences": [], "memories": [{"kind": "task_type", "content": "经常撰写技术综述"}]},
        ensure_ascii=False,
    )
    second = json.dumps(
        {"preferences": [], "memories": [{"kind": "task_type", "content": "常写技术综述"}]},
        ensure_ascii=False,
    )
    service = MemoryService(repository, ScriptedProvider([first, second]))

    await service.extract_from_task(
        "u1", query="写综述", result={"final_answer": "正文"}, task_id="t1"
    )
    await service.extract_from_task(
        "u1", query="再写一篇", result={"final_answer": "正文"}, task_id="t2"
    )

    memories = await repository.list_memories("u1")
    assert [memory.content for memory in memories] == ["经常撰写技术综述"]
    assert memories[0].source_task_id == "t1"


async def test_extract_skips_memory_that_duplicates_a_preference(
    repository: MemoryRepository,
) -> None:
    await repository.set_preference("u1", "style", "偏好学术严谨")
    payload = json.dumps(
        {
            "preferences": [],
            "memories": [{"kind": "fact", "content": "偏好学术严谨"}],
        },
        ensure_ascii=False,
    )
    service = MemoryService(repository, ScriptedProvider([payload]))

    await service.extract_from_task("u1", query="写综述", result={"final_answer": "正文"})

    assert await repository.list_memories("u1") == []


async def test_extract_reclassifies_preference_memory_as_fact(
    repository: MemoryRepository,
) -> None:
    payload = json.dumps(
        {
            "preferences": [],
            "memories": [{"kind": "preference", "content": "研究方向是 RAG 与知识图谱"}],
        },
        ensure_ascii=False,
    )
    service = MemoryService(repository, ScriptedProvider([payload]))

    await service.extract_from_task("u1", query="写综述", result={"final_answer": "正文"})

    memories = await repository.list_memories("u1")
    assert [(memory.kind, memory.content) for memory in memories] == [
        ("fact", "研究方向是 RAG 与知识图谱")
    ]


async def test_extract_prompt_includes_existing_memory(
    repository: MemoryRepository,
) -> None:
    await repository.set_preference("u1", "style", "偏好学术严谨")
    await repository.add_memory("u1", kind="fact", content="研究方向是 RAG")
    provider = ScriptedProvider(['{"preferences": [], "memories": []}'])
    service = MemoryService(repository, provider)

    await service.extract_from_task("u1", query="写综述", result={"final_answer": "正文"})

    prompt = provider.calls[0][-1].content
    assert "不要重复提取" in prompt
    assert "style=偏好学术严谨" in prompt
    assert "[fact] 研究方向是 RAG" in prompt


async def test_manual_add_memory_skips_near_duplicate(repository: MemoryRepository) -> None:
    service = MemoryService(repository)

    assert await service.add_memory("u1", kind="task_type", content="经常撰写技术综述") is not None
    assert await service.add_memory("u1", kind="task_type", content="常写技术综述") is None
    assert len(await repository.list_memories("u1")) == 1


async def test_manual_add_memory_skips_preference_duplicate(
    repository: MemoryRepository,
) -> None:
    service = MemoryService(repository)
    await service.set_preference("u1", "style", "偏好学术严谨")

    assert await service.add_memory("u1", kind="fact", content="偏好学术严谨") is None
    assert await repository.list_memories("u1") == []


async def test_manual_preference_uses_canonical_key(repository: MemoryRepository) -> None:
    service = MemoryService(repository)

    await service.set_preference("u1", "写作风格", "偏好学术严谨")
    assert await repository.get_preferences("u1") == {"style": "偏好学术严谨"}

    # 删除时旧写法同样能命中规范键
    assert await service.delete_preference("u1", "写作风格") is True
    assert await repository.get_preferences("u1") == {}


# --- 显式 API ---


def _client() -> TestClient:
    # 显式记忆 API 不需要 LLM，使用默认依赖装配即可
    return TestClient(create_app())


def test_memory_api_full_flow() -> None:
    with _client() as client:
        assert client.get("/api/memory").json() == {
            "user_id": "local-user",
            "preferences": {},
            "memories": [],
        }

        put = client.put("/api/memory/preferences/style", json={"value": "学术严谨"})
        assert put.status_code == 200
        assert put.json()["preferences"] == {"style": "学术严谨"}

        created = client.post(
            "/api/memory/memories", json={"kind": "task_type", "content": "常写综述"}
        )
        assert created.status_code == 201
        memory_id = created.json()["memory_id"]
        assert created.json()["source_task_id"] is None

        profile = client.get("/api/memory").json()
        assert profile["preferences"] == {"style": "学术严谨"}
        assert [m["content"] for m in profile["memories"]] == ["常写综述"]

        # 重复内容 -> 409
        assert (
            client.post(
                "/api/memory/memories", json={"kind": "task_type", "content": "常写综述"}
            ).status_code
            == 409
        )

        assert client.delete(f"/api/memory/memories/{memory_id}").status_code == 204
        assert client.delete(f"/api/memory/memories/{memory_id}").status_code == 404

        assert client.delete("/api/memory/preferences/style").status_code == 200
        assert client.delete("/api/memory/preferences/style").status_code == 404


def test_memory_api_is_scoped_by_user_header() -> None:
    with _client() as client:
        client.put(
            "/api/memory/preferences/style",
            json={"value": "严谨"},
            headers={"X-User-Id": "alice"},
        )
        alice = client.get("/api/memory", headers={"X-User-Id": "alice"}).json()
        bob = client.get("/api/memory", headers={"X-User-Id": "bob"}).json()

    assert alice["user_id"] == "alice"
    assert alice["preferences"] == {"style": "严谨"}
    assert bob["preferences"] == {}


def test_memory_api_validates_input() -> None:
    with _client() as client:
        assert client.put("/api/memory/preferences/style", json={"value": ""}).status_code == 422
        assert (
            client.post("/api/memory/memories", json={"kind": "fact", "content": ""}).status_code
            == 422
        )
