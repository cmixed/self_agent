"""知识库文档接口（AGENTS.md §18）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import get_document_service
from app.core.logging import get_logger
from app.models.schemas import (
    DeleteDocumentResponse,
    DocumentInfo,
    DocumentListResponse,
)
from app.services.document_service import DocumentService

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = get_logger(__name__)


@router.post("/upload", response_model=DocumentInfo)
async def upload_document(
    file: UploadFile = File(...),
    service: DocumentService = Depends(get_document_service),
) -> DocumentInfo:
    content = await file.read()
    return await service.ingest(filename=file.filename or "unnamed", content=content)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    service: DocumentService = Depends(get_document_service),
) -> DocumentListResponse:
    return DocumentListResponse(documents=service.list_documents())


@router.delete("/{document_id}", response_model=DeleteDocumentResponse)
async def delete_document(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> DeleteDocumentResponse:
    if not service.delete_document(document_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return DeleteDocumentResponse(document_id=document_id, status="deleted")
