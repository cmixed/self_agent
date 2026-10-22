"""从文档生成技能草稿：服务层 + API 契约测试。

全部使用假 Provider 与临时文件，不依赖真实 API（AGENTS.md §22）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fakes import ScriptedProvider
from fastapi.testclient import TestClient

from app.api.deps import get_skill_generation_service
from app.main import create_app
from app.memory.sqlite import SqliteDatabase
from app.services.skill_generation_service import (
    SkillDocumentEmptyError,
    SkillDocumentNotFoundError,
    SkillGenerationError,
    SkillGenerationService,
)
from app.services.skill_service import SkillService

DRAFT_PAYLOAD = {
    "name": "资料精读",
    "description": "当需要把一份长资料拆成可执行要点时使用",
    "content": (
        "你是资料精读助手。请按以下步骤处理给定资料：\n"
        "1) 先概括资料要解决的问题；\n"
        "2) 提取其中的方法、步骤与判断标准；\n"
        "3) 按「结论 - 依据 - 适用条件」输出。\n"
        "资料中不存在的信息不得编造。"
    ),
}
DRAFT_JSON = json.dumps(DRAFT_PAYLOAD, ensure_ascii=False)


class _FakeDocumentService:
    """只实现 ``document_file`` 的最小替身（生成流程只需要它）。"""

    def __init__(self, files: dict[str, tuple[Path, str]]) -> None:
        self._files = files

    async def document_file(self, document_id: str) -> tuple[Path, str] | None:
        return self._files.get(document_id)


def _service(
    tmp_path: Path,
    *,
    responses: list[str] | None = None,
    text: str = "# 方法\n\n1. 先读目录\n2. 再读正文\n",
    filename: str = "guide.md",
    max_chars: int = 12000,
) -> tuple[SkillGenerationService, ScriptedProvider]:
    document_path = tmp_path / "guide.md"
    document_path.write_text(text, encoding="utf-8")
    provider = ScriptedProvider(responses or [DRAFT_JSON])
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    service = SkillGenerationService(
        llm=provider,
        document_service=_FakeDocumentService({"doc-1": (document_path, filename)}),  # type: ignore[arg-type]
        skill_service=SkillService(database),
        max_chars=max_chars,
    )
    return service, provider


async def test_generate_returns_draft_and_source(tmp_path: Path) -> None:
    service, provider = _service(tmp_path)

    result = await service.generate(document_ids=["doc-1"])

    assert result.name == DRAFT_PAYLOAD["name"]
    assert result.description == DRAFT_PAYLOAD["description"]
    assert result.content == DRAFT_PAYLOAD["content"]
    assert result.source_filename == "guide.md"
    assert result.truncated is False
    assert result.duplicate_of is None
    assert provider.json_modes == [True]


async def test_generate_truncates_long_document(tmp_path: Path) -> None:
    service, provider = _service(tmp_path, text="甲" * 5000, max_chars=1000)

    result = await service.generate(document_ids=["doc-1"])

    assert result.truncated is True
    assert any("仅使用前 1000 字" in warning for warning in result.warnings)
    # 送进模型的内容应被截断到上限附近（含提示词开销）
    user_message = provider.calls[0][1].content
    assert len(user_message) < 1400


async def test_generate_reports_missing_document(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    with pytest.raises(SkillDocumentNotFoundError):
        await service.generate(document_ids=["missing"])


async def test_generate_reports_empty_document(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, text="   \n\n  ")

    with pytest.raises(SkillDocumentEmptyError):
        await service.generate(document_ids=["doc-1"])


async def test_generate_retries_once_on_invalid_json(tmp_path: Path) -> None:
    service, provider = _service(tmp_path, responses=["这不是 JSON", DRAFT_JSON])

    result = await service.generate(document_ids=["doc-1"])

    assert result.name == DRAFT_PAYLOAD["name"]
    assert len(provider.calls) == 2


async def test_generate_flags_duplicate_name(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    database = SqliteDatabase(tmp_path / "app.db")
    await SkillService(database).create_skill(
        name=DRAFT_PAYLOAD["name"], description="已有技能", content="已有指令"
    )

    result = await service.generate(document_ids=["doc-1"])

    assert result.duplicate_of is not None
    assert result.duplicate_of[1] == DRAFT_PAYLOAD["name"]


async def test_generate_warns_when_description_has_no_trigger(tmp_path: Path) -> None:
    payload = {**DRAFT_PAYLOAD, "description": "资料精读"}
    service, _ = _service(tmp_path, responses=[json.dumps(payload, ensure_ascii=False)])

    result = await service.generate(document_ids=["doc-1"])

    assert any("触发条件" in warning for warning in result.warnings)


async def test_generate_rejects_too_many_documents(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    with pytest.raises(SkillGenerationError, match="最多使用"):
        await service.generate(document_ids=["a", "b", "c", "d"])


def test_migration_adds_source_filename_to_existing_db(tmp_path: Path) -> None:
    """旧库（无 source_filename 列）启动后应被幂等补列。"""
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE skills (
            skill_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
            content TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            builtin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    SqliteDatabase(path).initialize()
    SqliteDatabase(path).initialize()  # 可重复执行

    connection = sqlite3.connect(path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(skills)")}
    connection.close()
    assert "source_filename" in columns


def test_api_generate_returns_draft_without_persisting(tmp_path: Path) -> None:
    document_path = tmp_path / "guide.md"
    document_path.write_text("# 方法\n\n1. 先读目录\n", encoding="utf-8")
    database = SqliteDatabase(tmp_path / "api.db")
    database.initialize()
    service = SkillGenerationService(
        llm=ScriptedProvider([DRAFT_JSON]),
        document_service=_FakeDocumentService({"doc-1": (document_path, "guide.md")}),  # type: ignore[arg-type]
        skill_service=SkillService(database),
    )

    app = create_app()
    app.dependency_overrides[get_skill_generation_service] = lambda: service
    with TestClient(app) as client:
        response = client.post(
            "/api/skills/generate",
            json={"document_ids": ["doc-1"], "hint": "偏流程"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["draft"]["name"] == DRAFT_PAYLOAD["name"]
        assert body["draft"]["source_filename"] == "guide.md"
        assert body["truncated"] is False
        # 草稿不应被落库
        skills = client.get("/api/skills").json()["skills"]
        assert all(skill["name"] != DRAFT_PAYLOAD["name"] for skill in skills)


def test_api_generate_maps_missing_document(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "api.db")
    database.initialize()
    service = SkillGenerationService(
        llm=ScriptedProvider([DRAFT_JSON]),
        document_service=_FakeDocumentService({}),  # type: ignore[arg-type]
        skill_service=SkillService(database),
    )

    app = create_app()
    app.dependency_overrides[get_skill_generation_service] = lambda: service
    with TestClient(app) as client:
        response = client.post("/api/skills/generate", json={"document_ids": ["nope"]})

    assert response.status_code == 404
    assert response.json()["error_type"] == "skill_document_not_found"


def test_create_skill_persists_source_filename(tmp_path: Path) -> None:
    with TestClient(create_app()) as client:
        created = client.post(
            "/api/skills",
            json={
                "name": "来自文档",
                "description": "当需要复用时使用",
                "content": "按步骤执行",
                "source_filename": "guide.md",
            },
        )
        assert created.status_code == 200
        assert created.json()["source_filename"] == "guide.md"

        listed = client.get("/api/skills").json()["skills"]
        record = next(skill for skill in listed if skill["name"] == "来自文档")
        assert record["source_filename"] == "guide.md"
