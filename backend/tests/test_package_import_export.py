"""统一导入导出：预设 / 长期记忆 / 知识库。

覆盖：JSON / zip 结构、预览去重、确认写入、重复导入跳过。
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fakes import FakeEmbeddingProvider

from app.memory.repository import MemoryRepository
from app.memory.sqlite import SqliteDatabase
from app.rag.store import ChromaStore
from app.services.category_service import CategoryService
from app.services.document_service import DocumentService
from app.services.knowledge_package_service import KnowledgePackageService
from app.services.memory_package_service import MemoryPackageService
from app.services.memory_service import MemoryService
from app.services.preset_package_service import (
    PresetPackageService,
    parse_preset_package,
)
from app.services.preset_service import PresetService
from app.transfer.errors import ImportPackageError, ImportPreviewExpiredError


def _database(tmp_path, name: str = "app.db") -> SqliteDatabase:
    database = SqliteDatabase(tmp_path / name)
    database.initialize()
    return database


def _documents(tmp_path, name: str = "kb") -> DocumentService:
    store = ChromaStore(
        persist_dir=tmp_path / name / "chroma",
        collection_name=f"{name}_collection",
        embedding_signature=FakeEmbeddingProvider().signature(),
    )
    return DocumentService(
        provider_factory=lambda: FakeEmbeddingProvider(),
        store=store,
        documents_dir=tmp_path / name / "documents",
        chunk_size=200,
        chunk_overlap=20,
    )


# --- 预设 ---


async def test_preset_export_import_roundtrip_and_skip_duplicates(tmp_path) -> None:
    source_db = _database(tmp_path, "source.db")
    source = PresetPackageService(
        PresetService(source_db), CategoryService(source_db), _documents(tmp_path, "source-kb")
    )
    presets = PresetService(source_db)
    await presets.create_preset(
        title="资料综述", description="归纳主题", query="根据资料写综述", auto_run=True
    )
    await presets.create_preset(title="对比分析", description="对比方案", query="对比资料中的方案")
    package = await source.export_all()

    payload = json.loads(package)
    assert payload["format"] == "self-agent-presets"
    assert [item["title"] for item in payload["presets"]] == ["资料综述", "对比分析"]

    target_db = _database(tmp_path, "target.db")
    target = PresetPackageService(
        PresetService(target_db), CategoryService(target_db), _documents(tmp_path, "target-kb")
    )
    token, preview = await target.preview(package)
    assert [item.title for item in preview.items] == ["资料综述", "对比分析"]
    imported, skipped = await target.confirm(token)
    assert [item.title for item in imported] == ["资料综述", "对比分析"]
    assert skipped == []

    # 再次导入同一个包：全部按重复跳过
    token, preview = await target.preview(package)
    assert preview.items == []
    assert sorted(preview.skipped) == ["对比分析", "资料综述"]
    imported, skipped = await target.confirm(token)
    assert imported == []
    assert sorted(skipped) == ["对比分析", "资料综述"]


def test_preset_parser_rejects_invalid_package() -> None:
    with pytest.raises(ImportPackageError):
        parse_preset_package(b"not json")
    with pytest.raises(ImportPackageError):
        parse_preset_package(json.dumps({"format": "other", "presets": []}).encode())
    with pytest.raises(ImportPackageError):
        parse_preset_package(
            json.dumps({"format": "self-agent-presets", "presets": [{"title": "x"}]}).encode()
        )


async def test_preset_preview_expires_once_consumed(tmp_path) -> None:
    db = _database(tmp_path)
    service = PresetPackageService(PresetService(db), CategoryService(db), _documents(tmp_path))
    token, _ = await service.preview(
        json.dumps(
            {
                "format": "self-agent-presets",
                "presets": [
                    {"title": "t", "description": "d", "query": "q"},
                ],
            }
        ).encode()
    )
    await service.confirm(token)
    with pytest.raises(ImportPreviewExpiredError):
        await service.confirm(token)


async def test_preset_scope_remaps_by_name_and_filename(tmp_path) -> None:
    """跨环境导入时源 id 不存在，按类别名 / 文件名映射到当前知识库。"""
    db = _database(tmp_path)
    categories = CategoryService(db)
    documents = _documents(tmp_path)
    category = await categories.create_category(name="论文")
    document = await documents.ingest(filename="paper.md", content=b"# RAG\n\ncontent")

    service = PresetPackageService(PresetService(db), categories, documents)
    payload = json.dumps(
        {
            "format": "self-agent-presets",
            "presets": [
                {
                    "title": "范围预设",
                    "description": "d",
                    "query": "q",
                    "scope": {
                        "category_ids": ["source-category"],
                        "document_ids": ["source-document"],
                        "category_names": ["论文"],
                        "document_filenames": ["paper.md"],
                    },
                }
            ],
        },
        ensure_ascii=False,
    ).encode()

    _, preview = await service.preview(payload)
    assert preview.items[0].category_ids == [category.category_id]
    assert preview.items[0].document_ids == [document.document_id]


# --- 长期记忆 ---


async def test_memory_export_import_merges_without_overwriting(tmp_path) -> None:
    db = _database(tmp_path)
    memory = MemoryService(MemoryRepository(db))
    await memory.set_preference("source", "style", "学术严谨")
    await memory.set_preference("source", "language", "中文")
    await memory.add_memory("source", kind="fact", content="经常撰写技术综述")

    package_service = MemoryPackageService(memory)
    package = await package_service.export_all("source")
    payload = json.loads(package)
    assert payload["format"] == "self-agent-memory"
    assert payload["preferences"]["style"] == "学术严谨"

    # 目标用户已有一条同键偏好：导入不得覆盖
    await memory.set_preference("target", "style", "通俗易懂")
    token, preview = await package_service.preview("target", package)
    assert "style" in preview.skipped_preferences
    assert preview.preferences == {"language": "中文"}
    assert [item.content for item in preview.memories] == ["经常撰写技术综述"]

    result = await package_service.confirm("target", token)
    assert result.preferences == ["language"]
    assert result.memories == ["经常撰写技术综述"]

    preferences, memories = await memory.get_profile("target")
    assert preferences["style"] == "通俗易懂"
    assert preferences["language"] == "中文"
    assert [item.content for item in memories] == ["经常撰写技术综述"]

    # 重复导入：全部跳过
    token, preview = await package_service.preview("target", package)
    assert preview.preferences == {}
    assert preview.memories == []
    result = await package_service.confirm("target", token)
    assert result.preferences == []
    assert result.memories == []


# --- 知识库 ---


async def test_knowledge_export_import_restores_document_and_categories(tmp_path) -> None:
    source_db = _database(tmp_path, "source.db")
    source_categories = CategoryService(source_db)
    source_docs = _documents(tmp_path, "source-kb")
    category = await source_categories.create_category(name="论文", description="课程论文")
    document = await source_docs.ingest(
        filename="paper.md", content="# RAG\n\n检索增强生成把外部资料注入模型。".encode()
    )
    await source_categories.set_document_categories(document.document_id, [category.category_id])

    source = KnowledgePackageService(source_docs, source_categories)
    package = await source.export_all()

    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "self-agent-knowledge-base"
        assert manifest["documents"][0]["filename"] == "paper.md"

    target_db = _database(tmp_path, "target.db")
    target_categories = CategoryService(target_db)
    target_docs = _documents(tmp_path, "target-kb")
    target = KnowledgePackageService(target_docs, target_categories)

    token, preview = await target.preview(package, filename="kb.zip")
    assert [item.filename for item in preview.documents] == ["paper.md"]
    assert [item.name for item in preview.categories] == ["论文"]

    result = await target.confirm(token)
    assert [item.filename for item in result.imported] == ["paper.md"]
    assert result.failed == []
    assert result.categories_created == ["论文"]

    imported = await target_docs.list_documents()
    assert len(imported) == 1
    mapping = await target_categories.document_category_map()
    categories = await target_categories.list_categories()
    assert mapping[imported[0].document_id] == [categories[0].category_id]

    # 重复导入同一个包：按内容 SHA-256 跳过
    token, preview = await target.preview(package)
    assert preview.documents == []
    assert preview.skipped == ["paper.md"]


async def test_knowledge_package_rejects_missing_manifest(tmp_path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("documents/0001.md", "content")
    service = KnowledgePackageService(_documents(tmp_path), CategoryService(_database(tmp_path)))
    with pytest.raises(ImportPackageError):
        await service.preview(buffer.getvalue())
