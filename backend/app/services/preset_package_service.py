"""预设任务包（JSON）的解析、预览与导出。

预设是纯配置（标题 / 说明 / query / 可选范围 / 直接运行），不需要像技能那样
携带附件，因此使用可读的 JSON 文件而不是 zip：

```json
{
  "format": "self-agent-presets",
  "version": 1,
  "presets": [
    {
      "title": "资料综述",
      "description": "...",
      "query": "...",
      "auto_run": false,
      "scope": { "category_ids": [], "document_ids": [] }
    }
  ]
}
```

导入采用与其它域一致的「先预览、后确认」两段式：预览暂存在内存中，
确认时才写入 SQLite；重复项（标题 + query 相同）会被跳过。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.memory.repository import PresetRecord
from app.services.category_service import CategoryService
from app.services.document_service import DocumentService
from app.services.preset_service import PresetService
from app.transfer.errors import ImportPackageError, ImportPackageTooLargeError
from app.transfer.package import decode_json, encode_json
from app.transfer.preview import PreviewStore

logger = get_logger(__name__)

PACKAGE_FORMAT = "self-agent-presets"
PACKAGE_VERSION = 1
MAX_PACKAGE_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_PRESETS = 200
MAX_TITLE_LENGTH = 40
MAX_DESCRIPTION_LENGTH = 120
MAX_QUERY_LENGTH = 2000


@dataclass
class PresetPackageItem:
    title: str
    description: str
    query: str
    output_mode: str = "generate"
    auto_run: bool = False
    category_ids: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    # 名称 / 文件名用于跨环境重映射（源 id 在目标环境不存在时按名称匹配）
    category_names: list[str] = field(default_factory=list)
    document_filenames: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PresetPackage:
    items: list[PresetPackageItem]
    warnings: list[str]
    source_filename: str | None = None


@dataclass(frozen=True)
class PresetPackagePreview:
    items: list[PresetPackageItem]
    skipped: list[str]
    warnings: list[str]
    source_filename: str | None = None


def _required_text(raw: dict, key: str, *, label: str, limit: int, index: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise ImportPackageError(f"第 {index} 条预设缺少有效的「{label}」")
    cleaned = value.strip()
    if not cleaned:
        raise ImportPackageError(f"第 {index} 条预设的「{label}」不能为空")
    if len(cleaned) > limit:
        raise ImportPackageError(f"第 {index} 条预设的「{label}」超过 {limit} 字，请先在原环境精简")
    return cleaned


def _id_list(
    raw: object, *, field_name: str, index: int, warnings: list[str], limit: int = 200
) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        warnings.append(f"第 {index} 条预设的 {field_name} 不是列表，已忽略")
        return []
    values: list[str] = []
    for value in raw:
        if not isinstance(value, str):
            warnings.append(f"第 {index} 条预设的 {field_name} 含非字符串项，已忽略")
            continue
        cleaned = value.strip()
        if cleaned and len(cleaned) <= limit and cleaned not in values:
            values.append(cleaned)
    return values


def _parse_scope(
    raw: object, *, index: int, warnings: list[str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    if raw is None:
        return [], [], [], []
    if not isinstance(raw, dict):
        warnings.append(f"第 {index} 条预设的 scope 格式不正确，已改为未绑定范围")
        return [], [], [], []
    return (
        _id_list(
            raw.get("category_ids"), field_name="category_ids", index=index, warnings=warnings
        ),
        _id_list(
            raw.get("document_ids"), field_name="document_ids", index=index, warnings=warnings
        ),
        _id_list(
            raw.get("category_names"),
            field_name="category_names",
            index=index,
            warnings=warnings,
            limit=40,
        ),
        _id_list(
            raw.get("document_filenames"),
            field_name="document_filenames",
            index=index,
            warnings=warnings,
            limit=200,
        ),
    )


def parse_preset_package(data: bytes, *, filename: str | None = None) -> PresetPackage:
    """解析并校验预设 JSON；结构不合法时抛出 :class:`ImportPackageError`。"""
    if len(data) > MAX_PACKAGE_BYTES:
        raise ImportPackageTooLargeError(
            f"预设文件超过 {MAX_PACKAGE_BYTES // (1024 * 1024)} MB 限制"
        )
    payload = decode_json(data, error_message="预设文件不是有效的 JSON")

    warnings: list[str] = []
    if isinstance(payload, dict):
        package_format = payload.get("format")
        if package_format is not None and package_format != PACKAGE_FORMAT:
            raise ImportPackageError(f"不支持的预设文件格式：{package_format}")
        version = payload.get("version", PACKAGE_VERSION)
        if not isinstance(version, int) or version < 1:
            raise ImportPackageError("预设文件版本号不合法")
        if version > PACKAGE_VERSION:
            raise ImportPackageError("预设文件版本过新，请升级应用后再导入")
        raw_items = payload.get("presets")
    elif isinstance(payload, list):
        # 兼容只包含预设数组的简单文件
        raw_items = payload
    else:
        raise ImportPackageError("预设文件顶层必须是对象或数组")

    if not isinstance(raw_items, list) or not raw_items:
        raise ImportPackageError("预设文件里没有可导入的预设")
    if len(raw_items) > MAX_PACKAGE_PRESETS:
        raise ImportPackageTooLargeError(f"一次最多导入 {MAX_PACKAGE_PRESETS} 条预设")

    items: list[PresetPackageItem] = []
    for index, raw in enumerate(raw_items, 1):
        if not isinstance(raw, dict):
            raise ImportPackageError(f"第 {index} 条预设不是对象")
        title = _required_text(raw, "title", label="标题", limit=MAX_TITLE_LENGTH, index=index)
        description = _required_text(
            raw, "description", label="说明", limit=MAX_DESCRIPTION_LENGTH, index=index
        )
        query = _required_text(raw, "query", label="任务内容", limit=MAX_QUERY_LENGTH, index=index)
        category_ids, document_ids, category_names, document_filenames = _parse_scope(
            raw.get("scope"), index=index, warnings=warnings
        )
        raw_mode = raw.get("output_mode")
        if raw_mode in (None, "generate", "verbatim"):
            output_mode = raw_mode or "generate"
        else:
            output_mode = "generate"
            warnings.append(f"第 {index} 条预设的输出方式无效，已按「生成内容」导入")
        items.append(
            PresetPackageItem(
                title=title,
                description=description,
                query=query,
                output_mode=output_mode,
                auto_run=raw.get("auto_run") is True,
                category_ids=category_ids,
                document_ids=document_ids,
                category_names=category_names,
                document_filenames=document_filenames,
            )
        )

    if filename and len(filename) > 260:
        filename = filename[:260]
    return PresetPackage(items=items, warnings=warnings, source_filename=filename)


def dump_preset_package(
    records: list[PresetRecord],
    *,
    category_names: dict[str, str] | None = None,
    document_filenames: dict[str, str] | None = None,
) -> bytes:
    """把全部预设导出为稳定的 JSON 结构（顺序即工作台展示顺序）。

    范围同时写入 id 与可读名称：目标环境 id 不一致时，导入可按类别名 /
    文件名重映射（跨机器迁移时尤其重要）。
    """
    category_names = category_names or {}
    document_filenames = document_filenames or {}

    presets: list[dict[str, object]] = []
    for record in records:
        scope: dict[str, object] | None = None
        if record.category_ids or record.document_ids:
            scope = {
                "category_ids": list(record.category_ids),
                "document_ids": list(record.document_ids),
                "category_names": [
                    category_names[value]
                    for value in record.category_ids
                    if value in category_names
                ],
                "document_filenames": [
                    document_filenames[value]
                    for value in record.document_ids
                    if value in document_filenames
                ],
            }
        presets.append(
            {
                "title": record.title,
                "description": record.description,
                "query": record.query,
                "output_mode": record.output_mode,
                "auto_run": record.auto_run,
                "scope": scope,
            }
        )

    payload = {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "presets": presets,
    }
    return encode_json(payload)


def _dedupe_key(title: str, query: str, output_mode: str = "generate") -> tuple[str, str, str]:
    return (
        output_mode,
        "".join(title.split()).casefold(),
        "".join(query.split()).casefold(),
    )


def _title_key(title: str) -> str:
    return "".join(title.split()).casefold()


class PresetPackageService:
    """导入预览（内存暂存）与导出。"""

    def __init__(
        self,
        presets: PresetService,
        categories: CategoryService,
        documents: DocumentService,
        *,
        ttl_seconds: float = 600,
    ) -> None:
        self._presets = presets
        self._categories = categories
        self._documents = documents
        self._previews: PreviewStore[PresetPackagePreview] = PreviewStore(ttl_seconds=ttl_seconds)

    @property
    def ttl_seconds(self) -> float:
        return self._previews.ttl_seconds

    async def preview(
        self, data: bytes, *, filename: str | None = None
    ) -> tuple[str, PresetPackagePreview]:
        package = await asyncio.to_thread(parse_preset_package, data, filename=filename)
        existing = await self._presets.list_presets()
        warnings = list(package.warnings)

        category_records = await self._categories.list_categories()
        known_categories = {item.category_id for item in category_records}
        category_by_name = {
            item.name.strip().casefold(): item.category_id for item in category_records
        }
        try:
            document_records = await self._documents.list_documents()
        except Exception as exc:  # 知识库不可用不应让导入预览整体失败
            known_documents = None
            document_by_filename: dict[str, str] = {}
            warnings.append("暂时无法读取知识库文档，范围中的文档 id 未校验")
            logger.warning(
                "预设导入读取文档失败",
                extra={"event": "preset_import_documents_failed", "error_type": type(exc).__name__},
            )
        else:
            known_documents = {item.document_id for item in document_records}
            document_by_filename = {}
            for item in document_records:
                document_by_filename.setdefault(item.filename.strip().casefold(), item.document_id)

        existing_keys = {_dedupe_key(item.title, item.query, item.output_mode) for item in existing}
        existing_title_keys = {_title_key(item.title) for item in existing}
        seen_keys: set[tuple[str, str, str]] = set()
        selected: list[PresetPackageItem] = []
        skipped: list[str] = []

        for index, item in enumerate(package.items, 1):
            self._clean_scope(
                item,
                index=index,
                known_categories=known_categories,
                category_by_name=category_by_name,
                known_documents=known_documents,
                document_by_filename=document_by_filename,
                warnings=warnings,
            )
            key = _dedupe_key(item.title, item.query, item.output_mode)
            if key in existing_keys or key in seen_keys:
                skipped.append(item.title)
                continue
            if _title_key(item.title) in existing_title_keys:
                warnings.append(f"第 {index} 条与现有预设标题相同，将作为独立预设导入")
            seen_keys.add(key)
            selected.append(item)

        preview = PresetPackagePreview(
            items=selected,
            skipped=skipped,
            warnings=warnings,
            source_filename=package.source_filename,
        )
        pending = await self._previews.put(preview)
        return pending.token, preview

    async def cancel(self, token: str) -> None:
        """丢弃预览（全局导入会在知识库落盘后重新生成预设预览）。"""
        await self._previews.discard(token)

    async def confirm(self, token: str) -> tuple[list[PresetRecord], list[str]]:
        preview = await self._previews.pop(
            token, expired_message="导入预览已过期，请重新上传预设文件"
        )

        # 预览到确认之间可能新增了预设：再次去重，避免重复写入
        existing = await self._presets.list_presets()
        existing_keys = {_dedupe_key(item.title, item.query, item.output_mode) for item in existing}
        imported: list[PresetRecord] = []
        skipped = list(preview.skipped)
        for item in preview.items:
            key = _dedupe_key(item.title, item.query, item.output_mode)
            if key in existing_keys:
                skipped.append(item.title)
                continue
            record = await self._presets.create_preset(
                title=item.title,
                description=item.description,
                query=item.query,
                output_mode=item.output_mode,
                category_ids=item.category_ids,
                document_ids=item.document_ids,
                auto_run=item.auto_run,
            )
            imported.append(record)
            existing_keys.add(key)
        return imported, skipped

    async def export_all(self) -> bytes:
        records = await self._presets.list_presets()
        categories = await self._categories.list_categories()
        category_names = {item.category_id: item.name for item in categories}
        try:
            documents = await self._documents.list_documents()
        except Exception as exc:
            logger.warning(
                "预设导出读取文档失败，范围只写 id",
                extra={"event": "preset_export_documents_failed", "error_type": type(exc).__name__},
            )
            document_filenames: dict[str, str] = {}
        else:
            document_filenames = {item.document_id: item.filename for item in documents}
        return await asyncio.to_thread(
            dump_preset_package,
            records,
            category_names=category_names,
            document_filenames=document_filenames,
        )

    def _clean_scope(
        self,
        item: PresetPackageItem,
        *,
        index: int,
        known_categories: set[str],
        category_by_name: dict[str, str],
        known_documents: set[str] | None,
        document_by_filename: dict[str, str],
        warnings: list[str],
    ) -> None:
        if (
            not item.category_ids
            and not item.document_ids
            and not item.category_names
            and not item.document_filenames
        ):
            return

        resolved_categories: list[str] = []
        missing = 0
        # 先按 id 保留（同环境恢复）；id 不存在时再用导出时的名称重映射
        for value in item.category_ids:
            if value in known_categories:
                if value not in resolved_categories:
                    resolved_categories.append(value)
            else:
                missing += 1
        for name in item.category_names:
            resolved = category_by_name.get(name.strip().casefold())
            if resolved is not None:
                if resolved not in resolved_categories:
                    resolved_categories.append(resolved)
            else:
                missing += 1

        resolved_documents: list[str] = []
        if known_documents is None:
            # 知识库暂不可读：保留原始 id，不做文档范围校验
            resolved_documents = list(dict.fromkeys(item.document_ids))
        else:
            for value in item.document_ids:
                if value in known_documents:
                    if value not in resolved_documents:
                        resolved_documents.append(value)
                else:
                    missing += 1
            for filename in item.document_filenames:
                resolved = document_by_filename.get(filename.strip().casefold())
                if resolved is not None:
                    if resolved not in resolved_documents:
                        resolved_documents.append(resolved)
                else:
                    missing += 1

        item.category_ids = resolved_categories
        item.document_ids = resolved_documents
        if missing:
            warnings.append(f"第 {index} 条范围中有 {missing} 项在当前知识库中不存在，已自动移除")
        if not item.category_ids and not item.document_ids:
            warnings.append(f"第 {index} 条的范围已失效，将改为未绑定范围")


__all__ = [
    "MAX_PACKAGE_BYTES",
    "PresetPackageItem",
    "PresetPackagePreview",
    "PresetPackageService",
    "dump_preset_package",
    "parse_preset_package",
]
