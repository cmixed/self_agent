"""一键备份 / 恢复：跨环境恢复知识库、技能、预设与长期记忆。"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile

from fakes import FakeEmbeddingProvider
from fastapi.testclient import TestClient

from app.api.deps import get_backup_service
from app.main import create_app
from app.memory.repository import MemoryRepository
from app.memory.sqlite import SqliteDatabase
from app.rag.store import ChromaStore
from app.services.backup_service import BackupService
from app.services.category_service import CategoryService
from app.services.document_service import DocumentService
from app.services.knowledge_package_service import KnowledgePackageService
from app.services.memory_package_service import MemoryPackageService
from app.services.memory_service import MemoryService
from app.services.preset_package_service import PresetPackageService
from app.services.preset_service import PresetService
from app.services.skill_service import SkillService
from app.skills.package import SkillPackageService
from app.skills.store import SkillFileStore


def _database(tmp_path, name: str) -> SqliteDatabase:
    database = SqliteDatabase(tmp_path / name)
    database.initialize()
    return database


def _documents(tmp_path, name: str) -> DocumentService:
    store = ChromaStore(
        persist_dir=tmp_path / name / "chroma",
        collection_name=f"{name}_collection",
        embedding_signature=FakeEmbeddingProvider().signature(),
    )
    return DocumentService(
        provider_factory=lambda: FakeEmbeddingProvider(),
        store=store,
        documents_dir=tmp_path / name / "documents",
    )


def _backup_service(tmp_path, prefix: str) -> tuple[BackupService, dict]:
    database = _database(tmp_path, f"{prefix}.db")
    categories = CategoryService(database)
    documents = _documents(tmp_path, f"{prefix}-kb")
    presets = PresetService(database)
    memory = MemoryService(MemoryRepository(database))
    skill_store = SkillFileStore(tmp_path / f"{prefix}-skills")
    skill_service = SkillService(skill_store)
    service = BackupService(
        PresetPackageService(presets, categories, documents),
        MemoryPackageService(memory),
        KnowledgePackageService(documents, categories),
        SkillPackageService(skill_store),
        skill_service,
    )
    return service, {
        "database": database,
        "categories": categories,
        "documents": documents,
        "presets": presets,
        "memory": memory,
        "skill_service": skill_service,
    }


async def test_backup_export_import_roundtrip(tmp_path) -> None:
    source, source_env = _backup_service(tmp_path, "source")
    category = await source_env["categories"].create_category(name="论文")
    document = await source_env["documents"].ingest(
        filename="paper.md", content=b"# RAG\n\nRetrieval augmented generation."
    )
    await source_env["categories"].set_document_categories(
        document.document_id, [category.category_id]
    )
    await source_env["presets"].create_preset(
        title="资料综述",
        description="归纳主题",
        query="根据资料写综述",
        category_ids=[category.category_id],
        document_ids=[document.document_id],
    )
    await source_env["memory"].set_preference("u", "style", "学术严谨")
    await source_env["memory"].add_memory("u", kind="fact", content="经常撰写技术综述")
    await source_env["skill_service"].create_skill(
        name="对比分析", description="比较多个方案", content="按维度比较"
    )

    backup = await source.export_all("u")
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "presets.json", "memory.json", "knowledge.zip"} <= names
        assert any(name.startswith("skills/") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "self-agent-backup"

    target, target_env = _backup_service(tmp_path, "target")
    token, preview = await target.preview("u", backup, filename="backup.zip")
    assert [section.key for section in preview.sections] == [
        "knowledge_base",
        "skills",
        "presets",
        "memory",
    ]

    result = await target.confirm("u", token)
    summaries = {section.key: section.summary for section in result.sections}
    assert "1 篇" in summaries["knowledge_base"]
    assert "1 个" in summaries["skills"]
    assert "1 条" in summaries["presets"]
    assert "1 条偏好" in summaries["memory"]

    documents = await target_env["documents"].list_documents()
    assert [item.filename for item in documents] == ["paper.md"]
    categories = await target_env["categories"].list_categories()
    assert [item.name for item in categories] == ["论文"]
    mapping = await target_env["categories"].document_category_map()
    assert mapping[documents[0].document_id] == [categories[0].category_id]

    presets = await target_env["presets"].list_presets()
    assert presets[0].title == "资料综述"
    # 源文档 id 在目标环境不存在，范围按文件名 / 类别名重映射
    assert presets[0].category_ids == [categories[0].category_id]
    assert presets[0].document_ids == [documents[0].document_id]

    preferences, memories = await target_env["memory"].get_profile("u")
    assert preferences["style"] == "学术严谨"
    assert [item.content for item in memories] == ["经常撰写技术综述"]

    skills = await target_env["skill_service"].list_skills()
    assert [item.name for item in skills] == ["对比分析"]


async def test_backup_import_twice_skips_duplicates(tmp_path) -> None:
    source, source_env = _backup_service(tmp_path, "source2")
    await source_env["documents"].ingest(filename="note.md", content=b"# note\n\ncontent")
    await source_env["presets"].create_preset(title="t", description="d", query="q")
    backup = await source.export_all("u")

    target, target_env = _backup_service(tmp_path, "target2")
    token, _ = await target.preview("u", backup)
    await target.confirm("u", token)

    token, preview = await target.preview("u", backup)
    assert preview.sections
    result = await target.confirm("u", token)
    summaries = {section.key: section.summary for section in result.sections}
    assert "跳过 1 篇" in summaries["knowledge_base"]
    assert "跳过 1 条" in summaries["presets"]
    assert len(await target_env["documents"].list_documents()) == 1
    assert len(await target_env["presets"].list_presets()) == 1


def test_backup_api_export_and_import(tmp_path) -> None:
    source, source_env = _backup_service(tmp_path, "api-source")
    asyncio.run(source_env["presets"].create_preset(title="备份预设", description="d", query="q"))
    target, _ = _backup_service(tmp_path, "api-target")
    current = {"service": source}

    app = create_app()
    app.dependency_overrides[get_backup_service] = lambda: current["service"]
    with TestClient(app) as client:
        exported = client.get("/api/backup/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("application/zip")
        assert "self-agent-backup" in exported.headers["content-disposition"]

        current["service"] = target
        preview = client.post(
            "/api/backup/import/preview",
            files={"file": ("backup.zip", exported.content, "application/zip")},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert any(section["key"] == "presets" for section in body["sections"])

        confirmed = client.post("/api/backup/import", json={"token": body["token"]})
        assert confirmed.status_code == 200
        keys = {section["key"] for section in confirmed.json()["sections"]}
        assert {"knowledge_base", "presets", "memory"} <= keys

        bad = client.post(
            "/api/backup/import/preview",
            files={"file": ("bad.zip", b"not zip", "application/zip")},
        )
        assert bad.status_code == 422
