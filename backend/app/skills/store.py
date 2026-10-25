"""技能目录存储。

文件是唯一内容源：

- ``SKILL.md``：YAML frontmatter（name/description）+ 正文；
- ``.skill-state.json``：应用内部状态（enabled/builtin/来源/时间戳）；
- ``references/``、``resources/``、``scripts/``：按需附件；脚本只保存不执行。

所有同步文件 IO 都通过 ``asyncio.to_thread`` 执行，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from app.core.logging import get_logger
from app.memory.repository import utc_now
from app.skills.errors import (
    BuiltinSkillProtectedError,
    SkillNameConflictError,
    SkillNotFoundError,
    SkillParseError,
    SkillResourceNameConflictError,
    SkillResourceNotFoundError,
)
from app.skills.frontmatter import parse_skill_markdown, render_skill_markdown
from app.skills.models import (
    SkillPackage,
    SkillPackageFile,
    SkillRecord,
    SkillResourceRecord,
)

logger = get_logger(__name__)

SKILL_FILENAME = "SKILL.md"
STATE_FILENAME = ".skill-state.json"
STATE_VERSION = 1
RESOURCE_ROOTS = ("references", "resources", "scripts")
ROOT_RESOURCE_FILES = frozenset({"reference.md"})
MAX_RESOURCE_CHARS = 200_000
MAX_RESOURCE_PATH_LENGTH = 260

_SKILL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _timestamp_from_path(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")


def normalize_resource_name(name: str) -> str:
    """把用户/导入包提供的附件名规范化为技能根目录下的 POSIX 相对路径。"""
    raw = name.strip().replace("\\", "/")
    if not raw:
        raise SkillResourceNameConflictError("附件名不能为空")
    if len(raw) > MAX_RESOURCE_PATH_LENGTH:
        raise SkillResourceNameConflictError("附件路径过长")
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise SkillResourceNameConflictError("附件路径不能是绝对路径")
    parts = list(path.parts)
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SkillResourceNameConflictError("附件路径不能包含 . 或 ..")
    if any(part.startswith(".") for part in parts):
        raise SkillResourceNameConflictError("附件路径不能以 . 开头")

    if len(parts) == 1:
        if parts[0] == "reference.md":
            return parts[0]
        parts = ["resources", parts[0]]
    if parts[0] not in RESOURCE_ROOTS:
        raise SkillResourceNameConflictError(
            "附件必须放在 references/、resources/ 或 scripts/ 下"
        )
    return "/".join(parts)


class SkillFileStore:
    """基于目录的技能仓库（文件即数据源）。"""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).expanduser().resolve()
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    async def ensure_root(self) -> None:
        await asyncio.to_thread(self._root.mkdir, parents=True, exist_ok=True)

    # --- 技能 ---

    async def list_skills(self, *, enabled_only: bool = False) -> list[SkillRecord]:
        return await asyncio.to_thread(self._list_skills, enabled_only)

    async def get_skill(self, skill_id: str) -> SkillRecord | None:
        return await asyncio.to_thread(self._get_skill, skill_id)

    async def create_skill(
        self,
        *,
        name: str,
        description: str,
        content: str,
        source_filename: str | None = None,
        skill_id: str | None = None,
        enabled: bool = True,
        builtin: bool = False,
        created_at: str | None = None,
        updated_at: str | None = None,
        extra: dict[str, Any] | None = None,
        resources: list[SkillPackageFile] | None = None,
    ) -> SkillRecord:
        return await asyncio.to_thread(
            self._create_skill,
            name,
            description,
            content,
            source_filename,
            skill_id,
            enabled,
            builtin,
            created_at,
            updated_at,
            extra,
            resources,
        )

    async def update_skill(
        self,
        skill_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        content: str | None = None,
        enabled: bool | None = None,
    ) -> SkillRecord | None:
        return await asyncio.to_thread(
            self._update_skill, skill_id, name, description, content, enabled
        )

    def create_skill_sync(
        self,
        *,
        name: str,
        description: str,
        content: str,
        source_filename: str | None = None,
        skill_id: str | None = None,
        enabled: bool = True,
        builtin: bool = False,
        created_at: str | None = None,
        updated_at: str | None = None,
        extra: dict[str, Any] | None = None,
        resources: list[SkillPackageFile] | None = None,
    ) -> SkillRecord:
        """同步创建（供迁移等已在线程中的场景调用）。"""
        return self._create_skill(
            name,
            description,
            content,
            source_filename,
            skill_id,
            enabled,
            builtin,
            created_at,
            updated_at,
            extra,
            resources,
        )

    async def delete_skill(self, skill_id: str) -> bool:
        return await asyncio.to_thread(self._delete_skill, skill_id)

    async def seed_from_directory(self, package_root: Path | str) -> int:
        """把内置技能包目录复制到 data/skills（已存在的不覆盖）。"""
        return await asyncio.to_thread(self._seed_from_directory, Path(package_root))

    # --- 附件 ---

    async def list_resources(self, skill_id: str) -> list[SkillResourceRecord]:
        return await asyncio.to_thread(self._list_resources, skill_id)

    async def list_resources_for_skills(
        self, skill_ids: list[str]
    ) -> dict[str, list[SkillResourceRecord]]:
        return await asyncio.to_thread(self._list_resources_for_skills, skill_ids)

    async def create_resource(
        self, skill_id: str, *, name: str, content: str
    ) -> SkillResourceRecord:
        return await asyncio.to_thread(self._create_resource, skill_id, name, content)

    async def update_resource(
        self,
        skill_id: str,
        resource_id: str,
        *,
        name: str | None = None,
        content: str | None = None,
    ) -> SkillResourceRecord | None:
        return await asyncio.to_thread(
            self._update_resource, skill_id, resource_id, name, content
        )

    async def delete_resource(self, skill_id: str, resource_id: str) -> bool:
        return await asyncio.to_thread(self._delete_resource, skill_id, resource_id)

    # --- 技能包 ---

    async def create_from_package(
        self,
        package: SkillPackage,
        *,
        skill_id: str | None = None,
    ) -> SkillRecord:
        return await asyncio.to_thread(self._create_from_package, package, skill_id)

    async def export_package(self, skill_id: str) -> bytes:
        return await asyncio.to_thread(self._export_package, skill_id)

    # --- 同步实现 ---

    def _skill_dir(self, skill_id: str) -> Path:
        if not _SKILL_ID_PATTERN.fullmatch(skill_id):
            raise SkillNotFoundError(f"技能不存在：{skill_id}")
        path = (self._root / skill_id).resolve()
        if path.parent != self._root:
            raise SkillNotFoundError(f"技能不存在：{skill_id}")
        return path

    def _require_skill_dir(self, skill_id: str) -> Path:
        skill_dir = self._skill_dir(skill_id)
        if not (skill_dir / SKILL_FILENAME).is_file():
            raise SkillNotFoundError(f"技能不存在：{skill_id}")
        return skill_dir

    def _iter_skill_dirs(self) -> list[Path]:
        if not self._root.is_dir():
            return []
        return sorted(
            path
            for path in self._root.iterdir()
            if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")
        )

    def _read_state(self, skill_dir: Path) -> dict[str, Any]:
        state_path = skill_dir / STATE_FILENAME
        default_created = _timestamp_from_path(skill_dir / SKILL_FILENAME)
        default = {
            "version": STATE_VERSION,
            "enabled": True,
            "builtin": False,
            "source_filename": None,
            "created_at": default_created,
            "updated_at": default_created,
        }
        if not state_path.is_file():
            return default
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "技能状态文件无法读取，使用默认值",
                extra={"skill_dir": str(skill_dir), "error": str(exc)},
            )
            return default
        if not isinstance(data, dict):
            return default
        return {
            "version": STATE_VERSION,
            "enabled": bool(data.get("enabled", True)),
            "builtin": bool(data.get("builtin", False)),
            "source_filename": data.get("source_filename") or None,
            "created_at": str(data.get("created_at") or default_created),
            "updated_at": str(data.get("updated_at") or default_created),
        }

    def _write_state(self, skill_dir: Path, state: dict[str, Any]) -> None:
        self._write_text(
            skill_dir / STATE_FILENAME,
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        )

    def _load_skill(self, skill_dir: Path) -> SkillRecord | None:
        skill_md = skill_dir / SKILL_FILENAME
        if not skill_md.is_file():
            return None
        try:
            parsed = parse_skill_markdown(skill_md.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SkillParseError) as exc:
            logger.warning(
                "技能目录无法解析，已跳过",
                extra={"skill_dir": str(skill_dir), "error": str(exc)},
            )
            return None
        state = self._read_state(skill_dir)
        resource_count, script_count = self._count_resources(skill_dir)
        return SkillRecord(
            skill_id=skill_dir.name,
            name=parsed.name,
            description=parsed.description,
            content=parsed.content,
            enabled=bool(state["enabled"]),
            builtin=bool(state["builtin"]),
            created_at=str(state["created_at"]),
            updated_at=str(state["updated_at"]),
            source_filename=state["source_filename"],
            resource_count=resource_count,
            script_count=script_count,
        )

    def _list_skills(self, enabled_only: bool) -> list[SkillRecord]:
        records = [
            record
            for skill_dir in self._iter_skill_dirs()
            if (record := self._load_skill(skill_dir)) is not None
        ]
        if enabled_only:
            records = [record for record in records if record.enabled]
        records.sort(key=lambda item: (item.created_at, item.skill_id))
        return records

    def _get_skill(self, skill_id: str) -> SkillRecord | None:
        try:
            skill_dir = self._skill_dir(skill_id)
        except SkillNotFoundError:
            return None
        return self._load_skill(skill_dir)

    def _unique_skill_id(self, preferred: str | None, name: str) -> str:
        candidate = (preferred or "").strip()
        if not _SKILL_ID_PATTERN.fullmatch(candidate):
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
            # 中文名等无法生成 slug 时用稳定随机 ID，避免出现 skill-skill 这类名字
            candidate = slug or f"skill-{uuid4().hex[:8]}"
        if not (self._root / candidate).exists():
            return candidate
        base = candidate
        for _ in range(20):
            candidate = f"{base}-{uuid4().hex[:4]}"
            if not (self._root / candidate).exists():
                return candidate
        raise SkillNameConflictError(f"无法生成唯一技能 ID：{base}")

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(temp_path, path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def _create_skill(
        self,
        name: str,
        description: str,
        content: str,
        source_filename: str | None,
        skill_id: str | None,
        enabled: bool,
        builtin: bool,
        created_at: str | None,
        updated_at: str | None,
        extra: dict[str, Any] | None,
        resources: list[SkillPackageFile] | None,
    ) -> SkillRecord:
        name = name.strip()
        description = description.strip()
        content = content.strip()
        if not name or not description or not content:
            raise ValueError("技能名称、适用场景与指令都不能为空")
        if skill_id is not None and not _SKILL_ID_PATTERN.fullmatch(skill_id):
            raise SkillNameConflictError(f"非法技能 ID：{skill_id}")

        self._root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target_id = self._unique_skill_id(skill_id, name)
            target = self._root / target_id
            now = utc_now()
            state = {
                "version": STATE_VERSION,
                "enabled": enabled,
                "builtin": builtin,
                "source_filename": source_filename,
                "created_at": created_at or now,
                "updated_at": updated_at or now,
            }
            self._write_skill_tree(
                target,
                name=name,
                description=description,
                content=content,
                extra=extra,
                state=state,
                resources=resources or [],
            )
        record = self._get_skill(target_id)
        assert record is not None
        return record

    def _write_skill_tree(
        self,
        target: Path,
        *,
        name: str,
        description: str,
        content: str,
        extra: dict[str, Any] | None,
        state: dict[str, Any],
        resources: list[SkillPackageFile],
    ) -> None:
        """先写临时目录，再整体 rename，避免半成品技能被扫描到。"""
        temp_dir = self._root / f".tmp-{uuid4().hex}"
        temp_dir.mkdir(parents=True)
        try:
            self._write_text(
                temp_dir / SKILL_FILENAME,
                render_skill_markdown(
                    name=name,
                    description=description,
                    content=content,
                    extra=extra,
                ),
            )
            for resource in resources:
                resource_path = normalize_resource_name(resource.name)
                if len(resource.content) > MAX_RESOURCE_CHARS:
                    raise ValueError(f"附件「{resource_path}」超过大小限制")
                self._write_text(temp_dir / resource_path, resource.content)
            self._write_state(temp_dir, state)
            if target.exists():
                raise SkillNameConflictError(f"技能已存在：{target.name}")
            temp_dir.rename(target)
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def _update_skill(
        self,
        skill_id: str,
        name: str | None,
        description: str | None,
        content: str | None,
        enabled: bool | None,
    ) -> SkillRecord | None:
        with self._lock:
            skill_dir = self._require_skill_dir(skill_id)
            existing = self._load_skill(skill_dir)
            if existing is None:
                return None
            state = self._read_state(skill_dir)
            now = utc_now()
            state["updated_at"] = now
            if enabled is not None:
                state["enabled"] = enabled

            if name is not None or description is not None or content is not None:
                parsed = parse_skill_markdown((skill_dir / SKILL_FILENAME).read_text("utf-8"))
                self._write_text(
                    skill_dir / SKILL_FILENAME,
                    render_skill_markdown(
                        name=(name or parsed.name).strip(),
                        description=(description or parsed.description).strip(),
                        content=(content if content is not None else parsed.content).strip(),
                        extra=parsed.extra,
                    ),
                )
            self._write_state(skill_dir, state)
            return self._get_skill(skill_id)

    def _delete_skill(self, skill_id: str) -> bool:
        with self._lock:
            skill_dir = self._skill_dir(skill_id)
            if not skill_dir.is_dir():
                return False
            record = self._load_skill(skill_dir)
            if record is not None and record.builtin:
                raise BuiltinSkillProtectedError("内置技能不可删除，可停用或编辑")
            shutil.rmtree(skill_dir)
            return True

    def _seed_from_directory(self, package_root: Path) -> int:
        if not package_root.is_dir():
            return 0
        count = 0
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            for source in sorted(package_root.iterdir()):
                if not source.is_dir() or source.name.startswith("."):
                    continue
                if not (source / SKILL_FILENAME).is_file():
                    continue
                target = self._root / source.name
                if target.exists():
                    continue
                temp_dir = self._root / f".tmp-{uuid4().hex}"
                try:
                    shutil.copytree(source, temp_dir)
                    state = {
                        "version": STATE_VERSION,
                        "enabled": True,
                        "builtin": True,
                        "source_filename": None,
                        "created_at": utc_now(),
                        "updated_at": utc_now(),
                    }
                    self._write_state(temp_dir, state)
                    temp_dir.rename(target)
                    count += 1
                except Exception:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    raise
        return count

    # --- 附件同步实现 ---

    def _resource_path(self, skill_dir: Path, resource_id: str) -> Path:
        relative = normalize_resource_name(resource_id)
        path = (skill_dir / relative).resolve()
        if not path.is_relative_to(skill_dir):
            raise SkillResourceNotFoundError(f"附件不存在：{resource_id}")
        if path.is_symlink():
            raise SkillResourceNotFoundError(f"附件不存在：{resource_id}")
        return path

    def _iter_resource_paths(self, skill_dir: Path) -> list[tuple[str, Path]]:
        found: list[tuple[str, Path]] = []
        for root_name in RESOURCE_ROOTS:
            base = skill_dir / root_name
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(skill_dir).as_posix()
                if any(part.startswith(".") for part in PurePosixPath(relative).parts):
                    continue
                found.append((relative, path))
        for name in ROOT_RESOURCE_FILES:
            path = skill_dir / name
            if path.is_file() and not path.is_symlink():
                found.append((name, path))
        found.sort(key=lambda item: item[0])
        return found

    def _count_resources(self, skill_dir: Path) -> tuple[int, int]:
        """统计 L3 附件数量（只走目录，不读正文）。脚本单独计数，供 UI 提示不执行。"""
        paths = self._iter_resource_paths(skill_dir)
        scripts = sum(1 for relative, _ in paths if relative.startswith("scripts/"))
        return len(paths), scripts

    def _resource_record(
        self, skill_id: str, relative: str, path: Path, content: str
    ) -> SkillResourceRecord:
        created_at = _timestamp_from_path(path)
        updated_at = created_at
        return SkillResourceRecord(
            resource_id=relative,
            skill_id=skill_id,
            name=relative,
            content=content,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _list_resources(self, skill_id: str) -> list[SkillResourceRecord]:
        skill_dir = self._require_skill_dir(skill_id)
        records: list[SkillResourceRecord] = []
        for relative, path in self._iter_resource_paths(skill_dir):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning(
                    "技能附件不是 UTF-8 文本，已跳过",
                    extra={"skill_id": skill_id, "resource": relative, "error": str(exc)},
                )
                continue
            records.append(self._resource_record(skill_id, relative, path, content))
        return records

    def _list_resources_for_skills(
        self, skill_ids: list[str]
    ) -> dict[str, list[SkillResourceRecord]]:
        grouped: dict[str, list[SkillResourceRecord]] = {}
        for skill_id in skill_ids:
            try:
                grouped[skill_id] = self._list_resources(skill_id)
            except SkillNotFoundError:
                grouped[skill_id] = []
        return grouped

    def _create_resource(self, skill_id: str, name: str, content: str) -> SkillResourceRecord:
        with self._lock:
            skill_dir = self._require_skill_dir(skill_id)
            relative = normalize_resource_name(name)
            path = skill_dir / relative
            if path.exists():
                raise SkillResourceNameConflictError(f"附件已存在：{relative}")
            if len(content) > MAX_RESOURCE_CHARS:
                raise ValueError("附件正文超过大小限制")
            self._write_text(path, content)
            self._touch_skill(skill_dir)
            return self._resource_record(skill_id, relative, path, content)

    def _update_resource(
        self,
        skill_id: str,
        resource_id: str,
        name: str | None,
        content: str | None,
    ) -> SkillResourceRecord | None:
        with self._lock:
            skill_dir = self._require_skill_dir(skill_id)
            old_relative = normalize_resource_name(resource_id)
            old_path = self._resource_path(skill_dir, old_relative)
            if not old_path.is_file():
                return None

            new_relative = normalize_resource_name(name) if name else old_relative
            new_path = skill_dir / new_relative
            if new_path != old_path and new_path.exists():
                raise SkillResourceNameConflictError(f"附件已存在：{new_relative}")

            if content is None:
                content = old_path.read_text(encoding="utf-8")
            if len(content) > MAX_RESOURCE_CHARS:
                raise ValueError("附件正文超过大小限制")

            # 先写新路径再删旧路径：中途失败时旧附件仍在，不会丢数据
            self._write_text(new_path, content)
            if new_path != old_path:
                old_path.unlink()
            self._touch_skill(skill_dir)
            return self._resource_record(skill_id, new_relative, new_path, content)

    def _delete_resource(self, skill_id: str, resource_id: str) -> bool:
        with self._lock:
            skill_dir = self._require_skill_dir(skill_id)
            relative = normalize_resource_name(resource_id)
            path = self._resource_path(skill_dir, relative)
            if not path.is_file():
                return False
            path.unlink()
            self._touch_skill(skill_dir)
            return True

    def _touch_skill(self, skill_dir: Path) -> None:
        state = self._read_state(skill_dir)
        state["updated_at"] = utc_now()
        self._write_state(skill_dir, state)

    # --- 技能包同步实现 ---

    def _create_from_package(self, package: SkillPackage, skill_id: str | None) -> SkillRecord:
        preferred = skill_id or package.suggested_skill_id
        resources = list(package.resources)
        return self._create_skill(
            package.name,
            package.description,
            package.content,
            package.source_filename,
            preferred,
            True,
            False,
            None,
            None,
            package.extra,
            resources,
        )

    def _export_package(self, skill_id: str) -> bytes:
        import io
        import zipfile

        skill_dir = self._require_skill_dir(skill_id)
        parsed = parse_skill_markdown((skill_dir / SKILL_FILENAME).read_text(encoding="utf-8"))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                f"{skill_id}/{SKILL_FILENAME}",
                render_skill_markdown(
                    name=parsed.name,
                    description=parsed.description,
                    content=parsed.content,
                    extra=parsed.extra,
                ),
            )
            for relative, path in self._iter_resource_paths(skill_dir):
                archive.write(path, f"{skill_id}/{relative}")
        return buffer.getvalue()
