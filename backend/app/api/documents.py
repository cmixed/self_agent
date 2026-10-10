"""知识库文档接口（AGENTS.md §18）。"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import get_category_service, get_document_service
from app.core.logging import get_logger
from app.models.schemas import (
    DeleteDocumentResponse,
    DocumentCategoriesUpdate,
    DocumentInfo,
    DocumentListResponse,
)
from app.services.category_service import CategoryNotFoundError, CategoryService
from app.services.document_service import DocumentService

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = get_logger(__name__)

# 显式映射，保证浏览器按文本内联渲染（而不是下载）
_MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return _MEDIA_TYPES.get(path.suffix.lower()) or guessed or "application/octet-stream"


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
    categories: CategoryService = Depends(get_category_service),
) -> DocumentListResponse:
    documents = await service.list_documents()
    mapping = await categories.document_category_map()
    for document in documents:
        document.category_ids = mapping.get(document.document_id, [])
    return DocumentListResponse(documents=documents)


@router.get("/{document_id}/content")
async def get_document_content(
    document_id: str,
    download: bool = Query(default=False, description="true=附件下载；false=内联预览"),
    service: DocumentService = Depends(get_document_service),
) -> FileResponse:
    """返回知识库文档的原文件，供在线查看或下载。

    只读取本地上传目录中该文档的原始文件；不读取向量库内容、不触发模型。
    """
    found = await service.document_file(document_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在或原文件已丢失"
        )
    path, filename = found
    return FileResponse(
        path,
        media_type=_media_type(path),
        filename=filename,
        content_disposition_type="attachment" if download else "inline",
    )


@router.delete("/{document_id}", response_model=DeleteDocumentResponse)
async def delete_document(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
    categories: CategoryService = Depends(get_category_service),
) -> DeleteDocumentResponse:
    if not await service.delete_document(document_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    # 文档已删除，顺手清理其分类映射（类别本身保留）
    await categories.purge_document(document_id)
    return DeleteDocumentResponse(document_id=document_id, status="deleted")


@router.put("/{document_id}/categories", response_model=None)
async def set_document_categories(
    document_id: str,
    payload: DocumentCategoriesUpdate,
    service: DocumentService = Depends(get_document_service),
    categories: CategoryService = Depends(get_category_service),
) -> dict[str, object]:
    """整组替换某文档的类别（多标签；前端复选框直接提交全量选择）。"""
    if await service.document_file(document_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    try:
        category_ids = await categories.set_document_categories(
            document_id, payload.category_ids
        )
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"document_id": document_id, "category_ids": category_ids}
