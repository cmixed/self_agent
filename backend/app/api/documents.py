"""知识库文档接口（AGENTS.md §18）。"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, Response

from app.api.deps import (
    build_memory_repository,
    get_category_service,
    get_current_user,
    get_document_service,
    get_knowledge_package_service,
)
from app.core.logging import get_logger
from app.memory.users import UserRecord
from app.models.schemas import (
    DeleteDocumentResponse,
    DocumentCategoriesUpdate,
    DocumentInfo,
    DocumentListResponse,
    DocumentPreferencesUpdate,
    DocumentVisibilityUpdate,
    ErrorResponse,
    ImportConfirmRequest,
    KnowledgeImportDocumentOut,
    KnowledgeImportFailureOut,
    KnowledgeImportPreview,
    KnowledgeImportResultOut,
)
from app.services.category_service import CategoryNotFoundError, CategoryService
from app.services.document_service import (
    VISIBLE_SCOPES,
    DocumentNotFoundError,
    DocumentPermissionError,
    DocumentService,
)
from app.services.knowledge_package_service import (
    MAX_PACKAGE_BYTES,
    KnowledgePackageService,
)
from app.transfer.errors import (
    ImportPackageError,
    ImportPackageTooLargeError,
    ImportPreviewExpiredError,
)
from app.transfer.package import export_filename

router = APIRouter(prefix="/api/documents", tags=["documents"])

# 成员级偏好：默认可见范围（team / private）
DEFAULT_VISIBILITY_KEY = "doc.default_visibility"
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


@router.get("/preferences", response_model=None)
async def get_document_preferences(
    user: UserRecord = Depends(get_current_user),
) -> dict[str, str]:
    """当前成员的文档偏好（默认可见范围）。"""
    preferences = await build_memory_repository().get_preferences(user.user_id)
    value = preferences.get(DEFAULT_VISIBILITY_KEY, "team")
    return {"default_visibility": value if value in VISIBLE_SCOPES else "team"}


@router.put("/preferences", response_model=None)
async def set_document_preferences(
    payload: DocumentPreferencesUpdate,
    user: UserRecord = Depends(get_current_user),
) -> dict[str, str]:
    if payload.default_visibility not in VISIBLE_SCOPES:
        raise HTTPException(status_code=422, detail="default_visibility 只能是 team 或 private")
    await build_memory_repository().set_preference(
        user.user_id, DEFAULT_VISIBILITY_KEY, payload.default_visibility
    )
    return {"default_visibility": payload.default_visibility}


@router.post("/upload", response_model=DocumentInfo)
async def upload_document(
    file: UploadFile = File(...),
    visibility: str = Form(default="team"),
    service: DocumentService = Depends(get_document_service),
    user: UserRecord = Depends(get_current_user),
) -> DocumentInfo:
    if visibility not in VISIBLE_SCOPES:
        raise HTTPException(status_code=422, detail="visibility 只能是 team 或 private")
    content = await file.read()
    return await service.ingest(
        filename=file.filename or "unnamed",
        content=content,
        owner_id=user.user_id,
        visibility=visibility,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    service: DocumentService = Depends(get_document_service),
    categories: CategoryService = Depends(get_category_service),
    user: UserRecord = Depends(get_current_user),
) -> DocumentListResponse:
    documents = await service.list_documents(user_id=user.user_id, is_admin=user.is_admin)
    mapping = await categories.document_category_map()
    for document in documents:
        document.category_ids = mapping.get(document.document_id, [])
    return DocumentListResponse(documents=documents)


def _import_error(status_code: int, error_type: str, detail: str) -> JSONResponse:
    body = ErrorResponse(error=error_type, error_type=error_type, detail=detail)
    return JSONResponse(status_code=status_code, content=body.model_dump())


@router.get("/export", response_model=None)
async def export_knowledge_base(
    service: KnowledgePackageService = Depends(get_knowledge_package_service),
    user: UserRecord = Depends(get_current_user),
) -> Response:
    """导出知识库（zip：文档原文件 + 类别 + 文档分类映射）。

    按导出者的可见范围过滤：团队成员只导出自己看得到的文档，管理员导出全部。
    """
    data = await service.export_all(user_id=user.user_id, is_admin=user.is_admin)
    filename = export_filename("knowledge-base", "zip")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import/preview", response_model=KnowledgeImportPreview)
async def preview_knowledge_import(
    file: UploadFile = File(...),
    service: KnowledgePackageService = Depends(get_knowledge_package_service),
) -> KnowledgeImportPreview | JSONResponse:
    data = await file.read(MAX_PACKAGE_BYTES + 1)
    try:
        token, preview = await service.preview(data, filename=file.filename)
    except ImportPackageTooLargeError as exc:
        return _import_error(413, exc.error_type, exc.message)
    except ImportPackageError as exc:
        return _import_error(422, exc.error_type, exc.message)

    return KnowledgeImportPreview(
        token=token,
        documents=[
            KnowledgeImportDocumentOut(
                filename=item.filename,
                size=item.size,
                category_ids=item.category_ids,
            )
            for item in preview.documents
        ],
        categories=[item.name for item in preview.categories],
        skipped=preview.skipped,
        warnings=preview.warnings,
        source_filename=preview.source_filename,
        expires_in=int(service.ttl_seconds),
    )


@router.post("/import", response_model=KnowledgeImportResultOut)
async def confirm_knowledge_import(
    payload: ImportConfirmRequest,
    service: KnowledgePackageService = Depends(get_knowledge_package_service),
    user: UserRecord = Depends(get_current_user),
) -> KnowledgeImportResultOut | JSONResponse:
    """确认导入；文档会重新解析、切分并建立向量索引，可能耗时较长。

    导入的文档归属为执行导入的成员（管理员导入则归管理员），默认团队共享。
    """
    try:
        result = await service.confirm(payload.token, owner_id=user.user_id)
    except ImportPreviewExpiredError as exc:
        return _import_error(409, exc.error_type, exc.message)
    return KnowledgeImportResultOut(
        imported=result.imported,
        skipped=result.skipped,
        failed=[
            KnowledgeImportFailureOut(filename=item.filename, message=item.message)
            for item in result.failed
        ],
        categories_created=result.categories_created,
    )


@router.get("/{document_id}/content")
async def get_document_content(
    document_id: str,
    download: bool = Query(default=False, description="true=附件下载；false=内联预览"),
    service: DocumentService = Depends(get_document_service),
    user: UserRecord = Depends(get_current_user),
) -> FileResponse:
    """返回知识库文档的原文件，供在线查看或下载。

    只读取本地上传目录中该文档的原始文件；不读取向量库内容、不触发模型。
    """
    info = await service.get_visible_document(
        document_id, user_id=user.user_id, is_admin=user.is_admin
    )
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在或你无权访问")
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


@router.patch("/{document_id}/visibility", response_model=DocumentInfo)
async def update_document_visibility(
    document_id: str,
    payload: DocumentVisibilityUpdate,
    service: DocumentService = Depends(get_document_service),
    user: UserRecord = Depends(get_current_user),
) -> DocumentInfo:
    """切换团队共享 / 仅自己可见（上传者或管理员）。"""
    try:
        return await service.set_visibility(
            document_id, payload.visibility, user_id=user.user_id, is_admin=user.is_admin
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文档不存在") from exc
    except DocumentPermissionError as exc:
        raise HTTPException(status_code=403, detail="只有上传者或管理员可以修改可见范围") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{document_id}", response_model=DeleteDocumentResponse)
async def delete_document(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
    categories: CategoryService = Depends(get_category_service),
    user: UserRecord = Depends(get_current_user),
) -> DeleteDocumentResponse:
    try:
        deleted = await service.delete_document(
            document_id, user_id=user.user_id, is_admin=user.is_admin
        )
    except DocumentPermissionError as exc:
        raise HTTPException(status_code=403, detail="只有上传者或管理员可以删除该文档") from exc
    if not deleted:
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
        category_ids = await categories.set_document_categories(document_id, payload.category_ids)
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"document_id": document_id, "category_ids": category_ids}
