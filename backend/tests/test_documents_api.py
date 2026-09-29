from __future__ import annotations

from pathlib import Path

from fakes import FakeEmbeddingProvider
from fastapi.testclient import TestClient

from app.api.deps import get_document_service
from app.main import create_app
from app.rag.store import ChromaStore
from app.services.document_service import DocumentService


def make_client(tmp_path: Path) -> TestClient:
    store = ChromaStore(
        persist_dir=tmp_path / "chroma",
        collection_name="api_kb",
        embedding_signature=FakeEmbeddingProvider().signature(),
    )
    service = DocumentService(
        provider_factory=lambda: FakeEmbeddingProvider(),
        store=store,
        documents_dir=tmp_path / "documents",
        chunk_size=120,
        chunk_overlap=20,
    )

    app = create_app()
    app.dependency_overrides[get_document_service] = lambda: service
    return TestClient(app)


def test_upload_list_delete_flow(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/api/documents/upload",
            files={"file": ("rag.md", "# RAG\n\n检索增强生成".encode(), "text/markdown")},
        )
        assert upload.status_code == 200
        document_id = upload.json()["document_id"]

        listed = client.get("/api/documents")
        assert listed.status_code == 200
        assert [item["document_id"] for item in listed.json()["documents"]] == [document_id]

        deleted = client.delete(f"/api/documents/{document_id}")
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "deleted"

        assert client.get("/api/documents").json()["documents"] == []
        assert client.delete(f"/api/documents/{document_id}").status_code == 404


def test_upload_unsupported_type_returns_415(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/documents/upload",
            files={"file": ("a.docx", b"data", "application/octet-stream")},
        )
    assert response.status_code == 415
    assert response.json()["error_type"] == "unsupported_document"
