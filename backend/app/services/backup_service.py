"""系统级一键备份 / 恢复。

备份包是一个 zip，内含各域已有的导出格式：

```text
manifest.json
presets.json            # 预设包（JSON）
memory.json             # 长期记忆包（JSON）
knowledge.zip           # 知识库包（zip：manifest + 原文件）
skills/<skill_id>.zip   # 用户自定义技能包（内置技能不导出）
```

导入采用与单域一致的「预览 → 确认」流程。恢复顺序为
**知识库 → 技能 → 预设 → 长期记忆**：先恢复知识库，预设的检索范围才能按
类别名 / 文件名重新映射到新文档。

不包含：任务历史、LLM Provider 密钥、浏览器 localStorage 设置（主题等）。
"""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.rag.loader import DocumentError
from app.services.knowledge_package_service import KnowledgePackageService
from app.services.memory_package_service import MemoryPackageService
from app.services.preset_package_service import PresetPackageService
from app.services.skill_service import SkillService
from app.skills.package import SkillPackageService
from app.transfer.errors import (
    ImportPackageError,
    ImportPackageTooLargeError,
    ImportPreviewExpiredError,
)
from app.transfer.package import decode_json, encode_json, open_zip
from app.transfer.preview import PreviewStore

logger = get_logger(__name__)

PACKAGE_FORMAT = "self-agent-backup"
PACKAGE_VERSION = 1
MAX_PACKAGE_BYTES = 300 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 900 * 1024 * 1024
MAX_PACKAGE_FILES = 1200
MANIFEST_NAME = "manifest.json"
PRESETS_NAME = "presets.json"
MEMORY_NAME = "memory.json"
KNOWLEDGE_NAME = "knowledge.zip"
SKILLS_PREFIX = "skills/"

_SAFE_SKILL_FILE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class BackupSkill:
    skill_id: str
    data: bytes


@dataclass(frozen=True)
class BackupPackage:
    presets: bytes | None
    memory: bytes | None
    knowledge: bytes | None
    skills: list[BackupSkill]
    warnings: list[str]
    source_filename: str | None = None


@dataclass(frozen=True)
class BackupSectionPreview:
    key: str
    label: str
    summary: str
    warnings: list[str]


@dataclass(frozen=True)
class BackupPreview:
    """全局预览；各域 token 留在对应的预览存储中。"""

    presets_bytes: bytes | None
    presets_token: str | None
    memory_token: str | None
    knowledge_token: str | None
    skill_tokens: list[str]
    sections: list[BackupSectionPreview]
    warnings: list[str]
    source_filename: str | None = None


@dataclass(frozen=True)
class BackupSectionResult:
    key: str
    label: str
    summary: str
    failed: list[str]


@dataclass(frozen=True)
class BackupImportResult:
    sections: list[BackupSectionResult]
    warnings: list[str]


def _safe_skill_file(skill_id: str, index: int) -> str:
    cleaned = _SAFE_SKILL_FILE.sub("_", skill_id).strip("._") or "skill"
    return f"{SKILLS_PREFIX}{index:03d}-{cleaned[:80]}.zip"


def _build_backup_zip(
    presets: bytes,
    memory: bytes,
    knowledge: bytes,
    skills: list[BackupSkill],
) -> bytes:
    buffer = io.BytesIO()
    skill_entries: list[dict[str, str]] = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PRESETS_NAME, presets)
        archive.writestr(MEMORY_NAME, memory)
        archive.writestr(KNOWLEDGE_NAME, knowledge)
        for index, skill in enumerate(skills, 1):
            member = _safe_skill_file(skill.skill_id, index)
            archive.writestr(member, skill.data)
            skill_entries.append({"skill_id": skill.skill_id, "file": member})
        manifest = {
            "format": PACKAGE_FORMAT,
            "version": PACKAGE_VERSION,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "sections": {
                "presets": PRESETS_NAME,
                "memory": MEMORY_NAME,
                "knowledge_base": KNOWLEDGE_NAME,
            },
            "skills": skill_entries,
            "notes": [
                "不包含内置技能、任务历史、LLM Provider 密钥与浏览器本地设置",
                "导入时会重新建立知识库向量索引",
            ],
        }
        archive.writestr(MANIFEST_NAME, encode_json(manifest))
    return buffer.getvalue()


def parse_backup_package(data: bytes, *, filename: str | None = None) -> BackupPackage:
    if len(data) > MAX_PACKAGE_BYTES:
        raise ImportPackageTooLargeError(
            f"备份文件超过 {MAX_PACKAGE_BYTES // (1024 * 1024)} MB 限制"
        )
    with open_zip(
        data,
        max_bytes=MAX_PACKAGE_BYTES,
        max_uncompressed_bytes=MAX_UNCOMPRESSED_BYTES,
        max_files=MAX_PACKAGE_FILES,
    ) as archive:
        names = {info.filename for info in archive.infolist() if not info.is_dir()}
        if MANIFEST_NAME not in names:
            raise ImportPackageError("备份包缺少 manifest.json")
        manifest = decode_json(
            archive.read(MANIFEST_NAME), error_message="备份 manifest.json 不是有效的 JSON"
        )
        if not isinstance(manifest, dict):
            raise ImportPackageError("备份 manifest.json 顶层必须是对象")
        package_format = manifest.get("format")
        if package_format is not None and package_format != PACKAGE_FORMAT:
            raise ImportPackageError(f"不支持的备份格式：{package_format}")
        version = manifest.get("version", PACKAGE_VERSION)
        if not isinstance(version, int) or version < 1:
            raise ImportPackageError("备份文件版本号不合法")
        if version > PACKAGE_VERSION:
            raise ImportPackageError("备份文件版本过新，请升级应用后再导入")

        raw_skills = manifest.get("skills", [])
        if not isinstance(raw_skills, list):
            raise ImportPackageError("备份 manifest 的 skills 必须是数组")
        skills: list[BackupSkill] = []
        referenced: set[str] = set()
        for index, raw in enumerate(raw_skills, 1):
            if not isinstance(raw, dict):
                raise ImportPackageError(f"第 {index} 个技能条目不是对象")
            skill_id = raw.get("skill_id")
            member = raw.get("file")
            if not isinstance(skill_id, str) or not skill_id.strip():
                raise ImportPackageError(f"第 {index} 个技能缺少 skill_id")
            if not isinstance(member, str) or not member.startswith(SKILLS_PREFIX):
                raise ImportPackageError(f"第 {index} 个技能路径不合法")
            if member not in names:
                raise ImportPackageError(f"备份缺少技能文件：{member}")
            if member in referenced:
                raise ImportPackageError(f"备份重复引用技能文件：{member}")
            referenced.add(member)
            skills.append(BackupSkill(skill_id=skill_id.strip(), data=archive.read(member)))

        presets = archive.read(PRESETS_NAME) if PRESETS_NAME in names else None
        memory = archive.read(MEMORY_NAME) if MEMORY_NAME in names else None
        knowledge = archive.read(KNOWLEDGE_NAME) if KNOWLEDGE_NAME in names else None
        if presets is None and memory is None and knowledge is None and not skills:
            raise ImportPackageError("备份里没有可导入的数据")

        known = {MANIFEST_NAME, PRESETS_NAME, MEMORY_NAME, KNOWLEDGE_NAME} | referenced
        ignored = sorted(names - known)
        warnings = []
        if ignored:
            warnings.append("已忽略备份中无法识别的文件：" + "、".join(ignored[:8]))

    if filename and len(filename) > 260:
        filename = filename[:260]
    return BackupPackage(
        presets=presets,
        memory=memory,
        knowledge=knowledge,
        skills=skills,
        warnings=warnings,
        source_filename=filename,
    )


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, (ImportPackageError, ImportPreviewExpiredError)):
        return exc.message
    if isinstance(exc, DocumentError):
        return str(exc)
    return "导入失败"


class BackupService:
    """一键备份导出与分域恢复。"""

    def __init__(
        self,
        presets: PresetPackageService,
        memory: MemoryPackageService,
        knowledge: KnowledgePackageService,
        skills: SkillPackageService,
        skill_service: SkillService,
        *,
        ttl_seconds: float = 600,
    ) -> None:
        self._presets = presets
        self._memory = memory
        self._knowledge = knowledge
        self._skills = skills
        self._skill_service = skill_service
        self._previews: PreviewStore[BackupPreview] = PreviewStore(ttl_seconds=ttl_seconds)

    @property
    def ttl_seconds(self) -> float:
        return self._previews.ttl_seconds

    async def export_all(self, user_id: str) -> bytes:
        presets = await self._presets.export_all()
        memory = await self._memory.export_all(user_id)
        knowledge = await self._knowledge.export_all()
        skills: list[BackupSkill] = []
        for record in await self._skill_service.list_skills():
            if record.builtin:
                continue
            skills.append(
                BackupSkill(
                    skill_id=record.skill_id,
                    data=await self._skills.export(record.skill_id),
                )
            )
        return await asyncio.to_thread(_build_backup_zip, presets, memory, knowledge, skills)

    async def preview(
        self, user_id: str, data: bytes, *, filename: str | None = None
    ) -> tuple[str, BackupPreview]:
        package = await asyncio.to_thread(parse_backup_package, data, filename=filename)
        sections: list[BackupSectionPreview] = []
        warnings = list(package.warnings)

        knowledge_token = None
        if package.knowledge is not None:
            knowledge_token, knowledge_preview = await self._knowledge.preview(package.knowledge)
            summary = (
                f"{len(knowledge_preview.documents)} 篇文档、"
                f"{len(knowledge_preview.categories)} 个类别"
            )
            if knowledge_preview.skipped:
                summary += f"（跳过 {len(knowledge_preview.skipped)} 篇重复）"
            sections.append(
                BackupSectionPreview(
                    key="knowledge_base",
                    label="知识库",
                    summary=summary,
                    warnings=knowledge_preview.warnings,
                )
            )
            warnings.extend(knowledge_preview.warnings)

        skill_tokens: list[str] = []
        skill_warnings: list[str] = []
        for skill in package.skills:
            skill_preview = await self._skills.preview(skill.data, filename=f"{skill.skill_id}.zip")
            skill_tokens.append(skill_preview.token)
            skill_warnings.extend(skill_preview.package.warnings)
        if package.skills:
            sections.append(
                BackupSectionPreview(
                    key="skills",
                    label="技能",
                    summary=f"{len(package.skills)} 个自定义技能",
                    warnings=skill_warnings,
                )
            )
            warnings.extend(skill_warnings)

        presets_token = None
        if package.presets is not None:
            presets_token, preset_preview = await self._presets.preview(package.presets)
            summary = f"{len(preset_preview.items)} 条预设"
            if preset_preview.skipped:
                summary += f"（跳过 {len(preset_preview.skipped)} 条重复）"
            sections.append(
                BackupSectionPreview(
                    key="presets",
                    label="预设",
                    summary=summary,
                    warnings=preset_preview.warnings,
                )
            )
            warnings.extend(preset_preview.warnings)
            if package.knowledge is not None:
                warnings.append("预设的检索范围会在知识库导入后重新映射")

        memory_token = None
        if package.memory is not None:
            memory_token, memory_preview = await self._memory.preview(user_id, package.memory)
            summary = (
                f"{len(memory_preview.preferences)} 条偏好、{len(memory_preview.memories)} 条记忆"
            )
            skipped = len(memory_preview.skipped_preferences) + len(memory_preview.skipped_memories)
            if skipped:
                summary += f"（跳过 {skipped} 条重复）"
            sections.append(
                BackupSectionPreview(
                    key="memory",
                    label="长期记忆",
                    summary=summary,
                    warnings=memory_preview.warnings,
                )
            )
            warnings.extend(memory_preview.warnings)

        preview = BackupPreview(
            presets_bytes=package.presets,
            presets_token=presets_token,
            memory_token=memory_token,
            knowledge_token=knowledge_token,
            skill_tokens=skill_tokens,
            sections=sections,
            warnings=warnings,
            source_filename=package.source_filename,
        )
        pending = await self._previews.put(preview)
        return pending.token, preview

    async def confirm(self, user_id: str, token: str) -> BackupImportResult:
        preview = await self._previews.pop(
            token, expired_message="导入预览已过期，请重新上传备份文件"
        )
        sections: list[BackupSectionResult] = []
        warnings: list[str] = []

        # 1. 知识库：后续预设范围依赖恢复后的文档 / 类别
        if preview.knowledge_token is not None:
            try:
                result = await self._knowledge.confirm(preview.knowledge_token)
                summary = f"导入 {len(result.imported)} 篇，跳过 {len(result.skipped)} 篇"
                failed = [f"{item.filename}：{item.message}" for item in result.failed]
                sections.append(
                    BackupSectionResult(
                        key="knowledge_base",
                        label="知识库",
                        summary=summary,
                        failed=failed,
                    )
                )
                warnings.extend(failed)
            except Exception as exc:
                sections.append(
                    BackupSectionResult(
                        key="knowledge_base",
                        label="知识库",
                        summary="未导入",
                        failed=[_safe_error(exc)],
                    )
                )
                warnings.append(f"知识库：{_safe_error(exc)}")

        # 2. 技能
        if preview.skill_tokens:
            imported = 0
            failed: list[str] = []
            for skill_token in preview.skill_tokens:
                try:
                    record = await self._skills.confirm(skill_token)
                    imported += 1
                    logger.info(
                        "备份技能已导入",
                        extra={
                            "event": "backup_skill_imported",
                            "status": "ok",
                            "skill_id": record.skill_id,
                        },
                    )
                except Exception as exc:
                    failed.append(_safe_error(exc))
            sections.append(
                BackupSectionResult(
                    key="skills",
                    label="技能",
                    summary=f"导入 {imported} 个",
                    failed=failed,
                )
            )
            warnings.extend(f"技能：{item}" for item in failed)

        # 3. 预设：在知识库落盘后重新预览，按名称 / 文件名重新映射范围
        if preview.presets_bytes is not None:
            if preview.presets_token is not None:
                await self._presets.cancel(preview.presets_token)
            try:
                new_token, _ = await self._presets.preview(preview.presets_bytes)
                imported, skipped = await self._presets.confirm(new_token)
                summary = f"导入 {len(imported)} 条，跳过 {len(skipped)} 条"
                sections.append(
                    BackupSectionResult(key="presets", label="预设", summary=summary, failed=[])
                )
            except Exception as exc:
                sections.append(
                    BackupSectionResult(
                        key="presets", label="预设", summary="未导入", failed=[_safe_error(exc)]
                    )
                )
                warnings.append(f"预设：{_safe_error(exc)}")

        # 4. 长期记忆
        if preview.memory_token is not None:
            try:
                result = await self._memory.confirm(user_id, preview.memory_token)
                summary = f"新增 {len(result.preferences)} 条偏好、{len(result.memories)} 条记忆"
                sections.append(
                    BackupSectionResult(key="memory", label="长期记忆", summary=summary, failed=[])
                )
            except Exception as exc:
                sections.append(
                    BackupSectionResult(
                        key="memory", label="长期记忆", summary="未导入", failed=[_safe_error(exc)]
                    )
                )
                warnings.append(f"长期记忆：{_safe_error(exc)}")

        logger.info(
            "一键恢复完成",
            extra={
                "event": "backup_imported",
                "status": "ok",
                "sections": len(sections),
            },
        )
        return BackupImportResult(sections=sections, warnings=warnings)


__all__ = [
    "MAX_PACKAGE_BYTES",
    "BackupImportResult",
    "BackupPackage",
    "BackupPreview",
    "BackupSectionPreview",
    "BackupSectionResult",
    "BackupService",
    "parse_backup_package",
]
