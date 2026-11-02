"""导入导出 API 约定：导出下载、预览 token、确认写入与错误映射。"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile

from fakes import FakeEmbeddingProvider
from fastapi.testclient import TestClient

from app.api.deps import (
    get_category_service,
    get_document_service,
    get_knowledge_package_service,
    get_memory_package_service,
    get_memory_service,
    get_preset_package_service,
    get_preset_service,
)
from app.main import create_app
from app.memory.repository import MemoryRepository
from app.memory.sqlite import SqliteDatabase
from app.rag.store import ChromaStore
from app.services.category_service import CategoryService
from app.services.document_service import DocumentService
from app.services.knowledge_package_service import KnowledgePackageService
from app.services.memory_package_service import MemoryPackageService
from app.services.memory_service import MemoryService
from app.services.preset_package_service import PresetPackageService
from app.services.preset_service import PresetService


def _database(tmp_path) -> SqliteDatabase:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    return database


def _documents(tmp_path) -> DocumentService:
    store = ChromaStore(
        persist_dir=tmp_path / "chroma",
        collection_name="package_api",
        embedding_signature=FakeEmbeddingProvider().signature(),
    )
    return DocumentService(
        provider_factory=lambda: FakeEmbeddingProvider(),
        store=store,
        documents_dir=tmp_path / "documents",
    )


def _preset_payload() -> bytes:
    return json.dumps(
        {
            "format": "self-agent-presets",
            "presets": [
                {
                    "title": "导入的预设",
                    "description": "来自备份",
                    "query": "根据资料写一篇综述",
                    "output_mode": "verbatim",
                    "auto_run": True,
                }
            ],
        },
        ensure_ascii=False,
    ).encode()


def test_preset_import_export_api(tmp_path) -> None:
    database = _database(tmp_path)
    presets = PresetService(database)
    categories = CategoryService(database)
    documents = _documents(tmp_path)
    package_service = PresetPackageService(presets, categories, documents)

    app = create_app()
    app.dependency_overrides[get_preset_service] = lambda: presets
    app.dependency_overrides[get_preset_package_service] = lambda: package_service

    with TestClient(app) as client:
        preview = client.post(
            "/api/presets/import/preview",
            files={"file": ("presets.json", _preset_payload(), "application/json")},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["presets"][0]["title"] == "导入的预设"
        assert body["presets"][0]["output_mode"] == "verbatim"
        token = body["token"]

        confirmed = client.post("/api/presets/import", json={"token": token})
        assert confirmed.status_code == 200
        assert [item["title"] for item in confirmed.json()["imported"]] == ["导入的预设"]
        assert confirmed.json()["imported"][0]["output_mode"] == "verbatim"

        listed = client.get("/api/presets").json()["presets"]
        listed_item = next(item for item in listed if item["title"] == "导入的预设")
        assert listed_item["output_mode"] == "verbatim"

        exported = client.get("/api/presets/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("application/json")
        payload = json.loads(exported.content)
        assert any(item["title"] == "导入的预设" for item in payload["presets"])
        exported_item = next(item for item in payload["presets"] if item["title"] == "导入的预设")
        assert exported_item["output_mode"] == "verbatim"

        # 重复预览：没有可导入项
        duplicate = client.post(
            "/api/presets/import/preview",
            files={"file": ("presets.json", _preset_payload(), "application/json")},
        )
        assert duplicate.json()["presets"] == []
        assert duplicate.json()["skipped_duplicates"] == ["导入的预设"]


def test_preset_import_rejects_bad_file(tmp_path) -> None:
    database = _database(tmp_path)
    package_service = PresetPackageService(
        PresetService(database), CategoryService(database), _documents(tmp_path)
    )
    app = create_app()
    app.dependency_overrides[get_preset_package_service] = lambda: package_service
    with TestClient(app) as client:
        response = client.post(
            "/api/presets/import/preview",
            files={"file": ("bad.json", b"not json", "application/json")},
        )
        assert response.status_code == 422
        assert response.json()["error_type"] == "import_package_invalid"


def test_memory_import_export_api(tmp_path) -> None:
    database = _database(tmp_path)
    memory = MemoryService(MemoryRepository(database))
    package_service = MemoryPackageService(memory)
    asyncio.run(memory.set_preference("local-user", "style", "学术严谨"))

    app = create_app()
    app.dependency_overrides[get_memory_service] = lambda: memory
    app.dependency_overrides[get_memory_package_service] = lambda: package_service

    payload = json.dumps(
        {
            "format": "self-agent-memory",
            "preferences": {"style": "通俗", "language": "中文"},
            "memories": [{"kind": "fact", "content": "经常撰写技术综述"}],
        },
        ensure_ascii=False,
    ).encode()

    with TestClient(app) as client:
        preview = client.post(
            "/api/memory/import/preview",
            files={"file": ("memory.json", payload, "application/json")},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["preferences"] == {"language": "中文"}
        assert body["skipped_preferences"] == ["style"]

        confirmed = client.post("/api/memory/import", json={"token": body["token"]})
        assert confirmed.status_code == 200
        assert confirmed.json()["preferences"] == ["language"]

        profile = client.get("/api/memory").json()
        assert profile["preferences"]["style"] == "学术严谨"
        assert profile["preferences"]["language"] == "中文"
        assert [item["content"] for item in profile["memories"]] == ["经常撰写技术综述"]

        exported = client.get("/api/memory/export")
        assert exported.status_code == 200
        assert json.loads(exported.content)["format"] == "self-agent-memory"


def _knowledge_package() -> bytes:
    manifest = {
        "format": "self-agent-knowledge-base",
        "version": 1,
        "categories": [
            {"category_id": "cat-source", "name": "论文", "description": "课程论文"},
        ],
        "documents": [
            {
                "file": "documents/0001.md",
                "filename": "paper.md",
                "category_ids": ["cat-source"],
            }
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("documents/0001.md", "# RAG\n\n检索增强生成。")
    return buffer.getvalue()


def test_knowledge_import_export_api(tmp_path) -> None:
    database = _database(tmp_path)
    documents = _documents(tmp_path)
    categories = CategoryService(database)
    package_service = KnowledgePackageService(documents, categories)

    app = create_app()
    app.dependency_overrides[get_document_service] = lambda: documents
    app.dependency_overrides[get_category_service] = lambda: categories
    app.dependency_overrides[get_knowledge_package_service] = lambda: package_service

    with TestClient(app) as client:
        preview = client.post(
            "/api/documents/import/preview",
            files={"file": ("kb.zip", _knowledge_package(), "application/zip")},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["documents"][0]["filename"] == "paper.md"
        assert body["categories"] == ["论文"]

        confirmed = client.post("/api/documents/import", json={"token": body["token"]})
        assert confirmed.status_code == 200
        assert [item["filename"] for item in confirmed.json()["imported"]] == ["paper.md"]
        assert confirmed.json()["categories_created"] == ["论文"]

        documents_list = client.get("/api/documents").json()["documents"]
        assert [item["filename"] for item in documents_list] == ["paper.md"]
        assert len(documents_list[0]["category_ids"]) == 1

        exported = client.get("/api/documents/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("application/zip")
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            assert "manifest.json" in archive.namelist()
