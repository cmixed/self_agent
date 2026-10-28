"""知识库包（zip）：文档原文件 + 类别 + 文档分类映射的导出与导入。

包结构：

```text
manifest.json
documents/0001.pdf
documents/0002.md
```

``manifest.json`` 记录类别、原始文件名、文件在 zip 中的路径以及文档的类别 id。
导入时会**重新解析、切分并建立向量索引**（与正常上传一致），因此不会复用
源机器的 Chroma 数据；类别按名称匹配，缺失的类别会自动创建。

去重使用文件内容的 SHA-256：重复导入同一个包不会产生重复文档。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from app.core.logging import get_logger
from app.models.schemas import DocumentInfo
from app.rag.loader import SUPPORTED_SUFFIXES, DocumentError
from app.services.category_service import CategoryNameConflictError, CategoryService
from app.services.document_service import DocumentService
from app.transfer.errors import ImportPackageError, ImportPackageTooLargeError
from app.transfer.package import decode_json, encode_json, open_zip
from app.transfer.preview import PreviewStore

logger = get_logger(__name__)

PACKAGE_FORMAT = "self-agent-knowledge-base"
PACKAGE_VERSION = 1
MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024
MAX_PACKAGE_FILES = 1000
MAX_DOCUMENTS = 500
MAX_CATEGORIES = 200
MAX_FILENAME_LENGTH = 200
MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class KnowledgeCategoryItem:
    category_id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class KnowledgeDocumentItem:
    member: str
    filename: str
    size: int
    sha256: str
    category_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgePackagePreview:
    """预览时保存原始 zip，确认阶段再读取文件内容。"""

    data: bytes
    documents: list[KnowledgeDocumentItem]
    categories: list[KnowledgeCategoryItem]
    skipped: list[str]
    warnings: list[str]
    source_filename: str | None = None


@dataclass(frozen=True)
class KnowledgeImportFailure:
    filename: str
    message: str


@dataclass(frozen=True)
class KnowledgeImportResult:
    imported: list[DocumentInfo]
    skipped: list[str]
    failed: list[KnowledgeImportFailure]
    categories_created: list[str]


def _text(raw: object, *, label: str, limit: int, index: int | None = None) -> str:
    if not isinstance(raw, str):
        prefix = f"第 {index} 条" if index is not None else ""
        raise ImportPackageError(f"{prefix}{label}必须是字符串")
    cleaned = raw.strip()
    if not cleaned:
        prefix = f"第 {index} 条" if index is not None else ""
        raise ImportPackageError(f"{prefix}{label}不能为空")
    if len(cleaned) > limit:
        raise ImportPackageError(f"{label}超过 {limit} 字")
    return cleaned


def _parse_manifest(data: bytes) -> tuple[list[KnowledgeCategoryItem], list[dict[str, object]]]:
    payload = decode_json(data, error_message="manifest.json 不是有效的 JSON")
    if not isinstance(payload, dict):
        raise ImportPackageError("manifest.json 顶层必须是对象")
    package_format = payload.get("format")
    if package_format is not None and package_format != PACKAGE_FORMAT:
        raise ImportPackageError(f"不支持的知识库文件格式：{package_format}")
    version = payload.get("version", PACKAGE_VERSION)
    if not isinstance(version, int) or version < 1:
        raise ImportPackageError("知识库文件版本号不合法")
    if version > PACKAGE_VERSION:
        raise ImportPackageError("知识库文件版本过新，请升级应用后再导入")

    raw_categories = payload.get("categories", [])
    if not isinstance(raw_categories, list):
        raise ImportPackageError("categories 必须是数组")
    if len(raw_categories) > MAX_CATEGORIES:
        raise ImportPackageTooLargeError(f"一次最多导入 {MAX_CATEGORIES} 个类别")
    categories: list[KnowledgeCategoryItem] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_categories, 1):
        if not isinstance(raw, dict):
            raise ImportPackageError(f"第 {index} 个类别不是对象")
        category_id = _text(raw.get("category_id"), label="类别 id", limit=128, index=index)
        if category_id in seen_ids:
            raise ImportPackageError(f"类别 id 重复：{category_id}")
        seen_ids.add(category_id)
        categories.append(
            KnowledgeCategoryItem(
                category_id=category_id,
                name=_text(raw.get("name"), label="类别名称", limit=40, index=index),
                description=_text(
                    raw.get("description", ""), label="类别说明", limit=200, index=index
                )
                if raw.get("description")
                else "",
            )
        )

    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list):
        raise ImportPackageError("manifest.json 缺少 documents 数组")
    if len(raw_documents) > MAX_DOCUMENTS:
        raise ImportPackageTooLargeError(f"一次最多导入 {MAX_DOCUMENTS} 篇文档")
    return categories, raw_documents


def _parse_zip_documents(
    archive: zipfile.ZipFile,
    raw_documents: list[dict[str, object]],
) -> tuple[list[KnowledgeDocumentItem], list[str]]:
    names = {info.filename for info in archive.infolist() if not info.is_dir()}
    referenced: set[str] = set()
    documents: list[KnowledgeDocumentItem] = []
    for index, raw in enumerate(raw_documents, 1):
        if not isinstance(raw, dict):
            raise ImportPackageError(f"第 {index} 篇文档不是对象")
        member = _text(raw.get("file"), label="文件路径", limit=200, index=index).replace("\\", "/")
        filename = _text(
            raw.get("filename"), label="文件名", limit=MAX_FILENAME_LENGTH, index=index
        )
        if (
            PurePosixPath(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or any(ord(char) < 32 for char in filename)
        ):
            raise ImportPackageError(f"第 {index} 篇文档的文件名不合法：{filename}")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ImportPackageError(f"第 {index} 篇文档格式不支持：{suffix or '(无扩展名)'}")
        if member not in names:
            raise ImportPackageError(f"manifest 引用的文件不存在：{member}")
        if member in referenced:
            raise ImportPackageError(f"manifest 重复引用同一个文件：{member}")
        referenced.add(member)
        raw_category_ids = raw.get("category_ids", [])
        if raw_category_ids is None:
            raw_category_ids = []
        if not isinstance(raw_category_ids, list):
            raise ImportPackageError(f"第 {index} 篇文档的 category_ids 必须是数组")
        category_ids: list[str] = []
        for value in raw_category_ids:
            if not isinstance(value, str) or not value.strip():
                continue
            cleaned = value.strip()
            if cleaned not in category_ids:
                category_ids.append(cleaned)
        content = archive.read(member)
        if not content:
            raise ImportPackageError(f"文档为空：{filename}")
        documents.append(
            KnowledgeDocumentItem(
                member=member,
                filename=filename,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                category_ids=category_ids,
            )
        )
    ignored = sorted(names - referenced - {MANIFEST_NAME})
    return documents, ignored


def _build_export_zip(
    documents: list[DocumentInfo],
    categories: list[tuple[str, str, str]],
    files: list[tuple[str, str]],
) -> bytes:
    """在线程中构建 zip（文件读取 + 压缩可能较慢）。"""
    buffer = io.BytesIO()
    manifest_documents: list[dict[str, object]] = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, (document, (path, filename)) in enumerate(zip(documents, files, strict=True), 1):
            suffix = Path(filename).suffix.lower()
            member = f"documents/{index:04d}{suffix}"
            archive.write(path, member)
            manifest_documents.append(
                {
                    "file": member,
                    "filename": filename,
                    "category_ids": list(document.category_ids),
                }
            )
        manifest = {
            "format": PACKAGE_FORMAT,
            "version": PACKAGE_VERSION,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "categories": [
                {"category_id": category_id, "name": name, "description": description}
                for category_id, name, description in categories
            ],
            "documents": manifest_documents,
        }
        archive.writestr(MANIFEST_NAME, encode_json(manifest))
    return buffer.getvalue()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class KnowledgePackageService:
    """知识库导出与导入（预览 token 内存暂存，确认时重新建立索引）。"""

    def __init__(
        self,
        documents: DocumentService,
        categories: CategoryService,
        *,
        ttl_seconds: float = 600,
    ) -> None:
        self._documents = documents
        self._categories = categories
        self._previews: PreviewStore[KnowledgePackagePreview] = PreviewStore(
            ttl_seconds=ttl_seconds
        )

    @property
    def ttl_seconds(self) -> float:
        return self._previews.ttl_seconds

    async def export_all(self) -> bytes:
        documents = await self._documents.list_documents()
        mapping = await self._categories.document_category_map()
        category_records = await self._categories.list_categories()
        for document in documents:
            document.category_ids = mapping.get(document.document_id, [])

        categories = [
            (record.category_id, record.name, record.description) for record in category_records
        ]
        files: list[tuple[str, str]] = []
        exported: list[DocumentInfo] = []
        for document in documents:
            found = await self._documents.document_file(document.document_id)
            if found is None:
                logger.warning(
                    "导出知识库时跳过缺失原文件的文档",
                    extra={
                        "event": "knowledge_export_missing_file",
                        "document_id": document.document_id,
                    },
                )
                continue
            path, filename = found
            files.append((str(path), filename))
            exported.append(document)
        return await asyncio.to_thread(_build_export_zip, exported, categories, files)

    async def preview(
        self, data: bytes, *, filename: str | None = None
    ) -> tuple[str, KnowledgePackagePreview]:
        categories, documents, warnings = await asyncio.to_thread(
            self._parse_zip_data, data, filename
        )
        known_hashes = await self._existing_hashes()

        selected: list[KnowledgeDocumentItem] = []
        skipped: list[str] = []
        seen_hashes: set[str] = set()
        for item in documents:
            if item.sha256 in known_hashes or item.sha256 in seen_hashes:
                skipped.append(item.filename)
                continue
            seen_hashes.add(item.sha256)
            selected.append(item)

        if filename and len(filename) > 260:
            filename = filename[:260]
        preview = KnowledgePackagePreview(
            data=data,
            documents=selected,
            categories=categories,
            skipped=skipped,
            warnings=warnings,
            source_filename=filename,
        )
        pending = await self._previews.put(preview)
        return pending.token, preview

    def _parse_zip_data(
        self, data: bytes, filename: str | None
    ) -> tuple[list[KnowledgeCategoryItem], list[KnowledgeDocumentItem], list[str]]:
        with open_zip(
            data,
            max_bytes=MAX_PACKAGE_BYTES,
            max_uncompressed_bytes=MAX_UNCOMPRESSED_BYTES,
            max_files=MAX_PACKAGE_FILES,
        ) as archive:
            infos = {info.filename for info in archive.infolist() if not info.is_dir()}
            if MANIFEST_NAME not in infos:
                raise ImportPackageError("知识库包缺少 manifest.json")
            categories, raw_documents = _parse_manifest(archive.read(MANIFEST_NAME))
            documents, ignored = _parse_zip_documents(archive, raw_documents)

        warnings: list[str] = []
        if ignored:
            warnings.append("已忽略未在 manifest 中引用的文件：" + "、".join(ignored[:8]))
        known_category_ids = {item.category_id for item in categories}
        for item in documents:
            missing = [value for value in item.category_ids if value not in known_category_ids]
            if missing:
                warnings.append(
                    f"《{item.filename}》引用了 {len(missing)} 个未导出的类别，已忽略"
                )
        return categories, documents, warnings

    async def _existing_hashes(self) -> set[str]:
        """已有文档内容的 SHA-256（用于跳过重复导入）。"""
        hashes: set[str] = set()
        for document in await self._documents.list_documents():
            found = await self._documents.document_file(document.document_id)
            if found is None:
                continue
            try:
                hashes.add(await asyncio.to_thread(_file_sha256, found[0]))
            except OSError:
                continue
        return hashes

    async def confirm(self, token: str) -> KnowledgeImportResult:
        preview = await self._previews.pop(
            token, expired_message="导入预览已过期，请重新上传知识库包"
        )
        if not preview.documents:
            # 全部是重复文档：不要为了一个空导入创建类别
            return KnowledgeImportResult(
                imported=[], skipped=list(preview.skipped), failed=[], categories_created=[]
            )
        category_mapping, categories_created = await self._resolve_categories(preview.categories)
        known_hashes = await self._existing_hashes()

        imported: list[DocumentInfo] = []
        skipped = list(preview.skipped)
        failed: list[KnowledgeImportFailure] = []
        with zipfile.ZipFile(io.BytesIO(preview.data)) as archive:
            for item in preview.documents:
                if item.sha256 in known_hashes:
                    skipped.append(item.filename)
                    continue
                try:
                    content = archive.read(item.member)
                    document = await self._documents.ingest(filename=item.filename, content=content)
                except Exception as exc:
                    message = str(exc) if isinstance(exc, DocumentError) else "导入失败"
                    failed.append(KnowledgeImportFailure(filename=item.filename, message=message))
                    logger.warning(
                        "知识库文档导入失败",
                        extra={
                            "event": "knowledge_import_failed",
                            "status": "error",
                            "filename": item.filename,
                            "error_type": type(exc).__name__,
                        },
                    )
                    continue

                resolved = [
                    category_mapping[value]
                    for value in item.category_ids
                    if value in category_mapping
                ]
                if resolved:
                    try:
                        await self._categories.set_document_categories(
                            document.document_id, resolved
                        )
                    except Exception:
                        # 文档已入库，分类失败只作为可读提示，不回滚文档
                        failed.append(
                            KnowledgeImportFailure(
                                filename=item.filename,
                                message="文档已导入，但分类失败，请在知识库中重新设置",
                            )
                        )
                imported.append(document)
                known_hashes.add(item.sha256)

        logger.info(
            "知识库已导入",
            extra={
                "event": "knowledge_imported",
                "status": "ok",
                "imported": len(imported),
                "skipped": len(skipped),
                "failed": len(failed),
            },
        )
        return KnowledgeImportResult(
            imported=imported,
            skipped=skipped,
            failed=failed,
            categories_created=categories_created,
        )

    async def _resolve_categories(
        self, categories: list[KnowledgeCategoryItem]
    ) -> tuple[dict[str, str], list[str]]:
        existing = await self._categories.list_categories()
        by_name = {record.name.strip().casefold(): record.category_id for record in existing}
        mapping: dict[str, str] = {}
        created: list[str] = []
        for item in categories:
            key = item.name.strip().casefold()
            resolved = by_name.get(key)
            if resolved is None:
                try:
                    record = await self._categories.create_category(
                        name=item.name, description=item.description
                    )
                except CategoryNameConflictError:
                    # 并发创建：重新按名称解析
                    current = await self._categories.list_categories()
                    by_name = {row.name.strip().casefold(): row.category_id for row in current}
                    resolved = by_name.get(key)
                else:
                    resolved = record.category_id
                    by_name[key] = resolved
                    created.append(record.name)
            if resolved is not None:
                mapping[item.category_id] = resolved
        return mapping, created


__all__ = [
    "MAX_PACKAGE_BYTES",
    "KnowledgeImportFailure",
    "KnowledgeImportResult",
    "KnowledgePackagePreview",
    "KnowledgePackageService",
]
