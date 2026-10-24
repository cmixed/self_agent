"""标准技能包（zip / SKILL.md + 附件）解析、预览与导出。"""

from __future__ import annotations

import asyncio
import io
import posixpath
import re
import stat
import time
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import uuid4

from app.core.logging import get_logger
from app.skills.errors import (
    SkillImportExpiredError,
    SkillPackageError,
    SkillPackageTooLargeError,
)
from app.skills.frontmatter import parse_skill_markdown
from app.skills.models import SkillPackage, SkillPackageFile, SkillRecord
from app.skills.store import (
    MAX_RESOURCE_PATH_LENGTH,
    RESOURCE_ROOTS,
    ROOT_RESOURCE_FILES,
    SkillFileStore,
    normalize_resource_name,
)

logger = get_logger(__name__)

MAX_PACKAGE_BYTES = 10 * 1024 * 1024
MAX_PACKAGE_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_PACKAGE_FILES = 80
MAX_PACKAGE_FILE_CHARS = 200_000
MAX_PACKAGE_TOTAL_CHARS = 1_000_000
MAX_SKILL_NAME_LENGTH = 60
MAX_SKILL_DESCRIPTION_LENGTH = 200

_SKILL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


@dataclass(frozen=True)
class SkillPackagePreview:
    """一次待确认的导入预览。"""

    token: str
    package: SkillPackage
    expires_at: float


def _safe_zip_member(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        raise SkillPackageError(f"技能包包含绝对路径：{name}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise SkillPackageError(f"技能包包含非法路径：{name}")
    if len(normalized) > MAX_RESOURCE_PATH_LENGTH:
        raise SkillPackageError(f"技能包文件路径过长：{name}")
    return normalized


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK


def parse_skill_package(data: bytes, *, filename: str | None = None) -> SkillPackage:
    """解析 zip 技能包；不符合标准目录约定时抛出 :class:`SkillPackageError`。"""
    if len(data) > MAX_PACKAGE_BYTES:
        raise SkillPackageTooLargeError(
            f"技能包超过 {MAX_PACKAGE_BYTES // (1024 * 1024)} MB 限制"
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SkillPackageError("上传的文件不是有效的 zip 技能包") from exc

    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_PACKAGE_FILES:
            raise SkillPackageTooLargeError(f"技能包最多包含 {MAX_PACKAGE_FILES} 个文件")
        if sum(info.file_size for info in infos) > MAX_PACKAGE_UNCOMPRESSED_BYTES:
            raise SkillPackageTooLargeError("技能包解压后超过大小限制")
        for info in infos:
            if _is_symlink(info):
                raise SkillPackageError(f"技能包不能包含符号链接：{info.filename}")

        members: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            name = _safe_zip_member(info.filename)
            members[name] = info

        skill_files = [name for name in members if PurePosixPath(name).name == "SKILL.md"]
        if not skill_files:
            raise SkillPackageError("技能包缺少 SKILL.md")
        if len(skill_files) > 1:
            raise SkillPackageError("技能包只能包含一个 SKILL.md")
        skill_file = skill_files[0]
        root = posixpath.dirname(skill_file)
        prefix = f"{root}/" if root else ""

        try:
            skill_text = archive.read(members[skill_file]).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SkillPackageError("SKILL.md 不是 UTF-8 文本") from exc
        parsed = parse_skill_markdown(skill_text)

        warnings: list[str] = []
        resources: list[SkillPackageFile] = []
        seen: set[str] = set()
        ignored: list[str] = []
        scripts: list[str] = []
        total_chars = 0

        for name, info in members.items():
            if name == skill_file:
                continue
            if not name.startswith(prefix):
                ignored.append(name)
                continue
            relative = name[len(prefix) :]
            if relative == "SKILL.md":
                continue
            if relative.startswith("__MACOSX/") or relative.endswith("/.DS_Store"):
                continue
            if relative == ".skill-state.json":
                warnings.append("已忽略应用内部状态文件 .skill-state.json")
                continue

            first = PurePosixPath(relative).parts[0]
            if relative not in ROOT_RESOURCE_FILES and first not in RESOURCE_ROOTS:
                ignored.append(relative)
                continue

            try:
                content = archive.read(info).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SkillPackageError(f"附件「{relative}」不是 UTF-8 文本") from exc
            if len(content) > MAX_PACKAGE_FILE_CHARS:
                raise SkillPackageTooLargeError(f"附件「{relative}」超过单文件大小限制")
            total_chars += len(content)
            if total_chars > MAX_PACKAGE_TOTAL_CHARS:
                raise SkillPackageTooLargeError("技能包附件总字数超过限制")
            normalized = normalize_resource_name(relative)
            if normalized in seen:
                raise SkillPackageError(f"技能包包含重复附件：{normalized}")
            seen.add(normalized)
            resources.append(SkillPackageFile(name=normalized, content=content.rstrip()))
            if normalized.startswith("scripts/"):
                scripts.append(normalized)

        if ignored:
            warnings.append("已忽略不在标准目录下的文件：" + "、".join(sorted(ignored)[:8]))
        if scripts:
            warnings.append(
                "技能包包含脚本文件，系统会保存但不会执行："
                + "、".join(sorted(scripts)[:8])
            )

        name = parsed.name.strip()
        description = parsed.description.strip()
        if len(name) > MAX_SKILL_NAME_LENGTH:
            name = name[:MAX_SKILL_NAME_LENGTH].rstrip()
            warnings.append(f"名称超过 {MAX_SKILL_NAME_LENGTH} 字，已截断")
        if len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
            description = description[:MAX_SKILL_DESCRIPTION_LENGTH].rstrip()
            warnings.append(f"适用场景超过 {MAX_SKILL_DESCRIPTION_LENGTH} 字，已截断")

        suggested = PurePosixPath(root).name if root else None
        if suggested and not _SKILL_ID_PATTERN.fullmatch(suggested):
            suggested = None
        if filename and len(filename) > 260:
            filename = filename[:260]

        return SkillPackage(
            name=name,
            description=description,
            content=parsed.content,
            resources=resources,
            suggested_skill_id=suggested,
            source_filename=filename,
            warnings=warnings,
            extra=parsed.extra,
        )


class SkillPackageService:
    """导入预览（内存暂存）与导出。"""

    def __init__(self, store: SkillFileStore, *, ttl_seconds: float = 600) -> None:
        self._store = store
        self._ttl_seconds = max(0.001, ttl_seconds)
        self._pending: dict[str, SkillPackagePreview] = {}
        self._lock = asyncio.Lock()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    async def preview(self, data: bytes, *, filename: str | None = None) -> SkillPackagePreview:
        package = await asyncio.to_thread(parse_skill_package, data, filename=filename)
        existing = await self._store.list_skills()
        normalized = "".join(package.name.split()).lower()
        if any("".join(skill.name.split()).lower() == normalized for skill in existing):
            package.warnings.append("已存在同名技能；导入后会创建一个独立技能")

        token = uuid4().hex
        preview = SkillPackagePreview(
            token=token,
            package=package,
            expires_at=time.monotonic() + self._ttl_seconds,
        )
        async with self._lock:
            self._cleanup_expired()
            self._pending[token] = preview
        return preview

    async def confirm(self, token: str) -> SkillRecord:
        async with self._lock:
            self._cleanup_expired()
            preview = self._pending.pop(token, None)
        if preview is None:
            raise SkillImportExpiredError("导入预览已过期，请重新上传技能包")
        return await self._store.create_from_package(preview.package)

    async def export(self, skill_id: str) -> bytes:
        return await self._store.export_package(skill_id)

    def _cleanup_expired(self) -> None:
        now = time.monotonic()
        expired = [token for token, item in self._pending.items() if item.expires_at <= now]
        for token in expired:
            self._pending.pop(token, None)
