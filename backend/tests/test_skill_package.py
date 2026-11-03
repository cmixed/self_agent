"""技能包解析 / 导入预览 / 导出 round-trip。"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from app.skills.errors import (
    SkillImportExpiredError,
    SkillNotFoundError,
    SkillPackageError,
    SkillPackageTooLargeError,
    SkillParseError,
)
from app.skills.models import SkillPackageFile
from app.skills.package import SkillPackageService, parse_skill_package
from app.skills.store import SkillFileStore

SKILL_MD = """---
name: 示例技能
description: 当需要演示技能包导入时使用
---

你是示例技能。请按步骤执行。
"""


def _zip(files: Mapping[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(name, data)
    return buffer.getvalue()


def test_parse_minimal_package() -> None:
    data = _zip({"my-skill/SKILL.md": SKILL_MD})

    package = parse_skill_package(data, filename="my-skill.zip")

    assert package.name == "示例技能"
    assert package.description.startswith("当需要")
    assert package.content == "你是示例技能。请按步骤执行。"
    assert package.suggested_skill_id == "my-skill"
    assert package.source_filename == "my-skill.zip"
    assert package.resources == []


def test_parse_package_with_standard_resource_directories() -> None:
    data = _zip(
        {
            "my-skill/SKILL.md": SKILL_MD,
            "my-skill/references/background.md": "背景资料",
            "my-skill/resources/template.md": "模板",
            "my-skill/scripts/tool.py": "print('hi')\n",
            "my-skill/reference.md": "根目录参考",
        }
    )

    package = parse_skill_package(data)

    assert [item.name for item in package.resources] == [
        "references/background.md",
        "resources/template.md",
        "scripts/tool.py",
        "reference.md",
    ]
    assert any("不会执行" in warning for warning in package.warnings)


def test_parse_package_at_zip_root() -> None:
    data = _zip({"SKILL.md": SKILL_MD, "resources/checklist.md": "检查项"})

    package = parse_skill_package(data)

    assert package.suggested_skill_id is None
    assert [item.name for item in package.resources] == ["resources/checklist.md"]


def test_parse_rejects_missing_skill_md() -> None:
    with pytest.raises(SkillPackageError, match="缺少 SKILL.md"):
        parse_skill_package(_zip({"my-skill/readme.md": "无技能"}))


def test_parse_rejects_multiple_skill_md() -> None:
    with pytest.raises(SkillPackageError, match="只能包含一个"):
        parse_skill_package(_zip({"a/SKILL.md": SKILL_MD, "b/SKILL.md": SKILL_MD}))


def test_parse_rejects_invalid_frontmatter() -> None:
    with pytest.raises(SkillParseError):
        parse_skill_package(_zip({"s/SKILL.md": "没有 frontmatter\n"}))


def test_parse_rejects_zip_slip() -> None:
    with pytest.raises(SkillPackageError, match="非法路径"):
        parse_skill_package(_zip({"s/SKILL.md": SKILL_MD, "s/../../evil.md": "x"}))


def test_parse_rejects_binary_attachment() -> None:
    with pytest.raises(SkillPackageError, match="不是 UTF-8"):
        parse_skill_package(
            _zip({"s/SKILL.md": SKILL_MD, "s/resources/blob.md": b"\xff\xfe\x00\x01"})
        )


def test_parse_rejects_too_many_files() -> None:
    files = {"s/SKILL.md": SKILL_MD}
    files.update({f"s/resources/f{i}.md": "x" for i in range(90)})
    with pytest.raises(SkillPackageTooLargeError):
        parse_skill_package(_zip(files))


def test_parse_ignores_non_standard_paths() -> None:
    data = _zip({"s/SKILL.md": SKILL_MD, "s/notes/random.md": "忽略我"})

    package = parse_skill_package(data)

    assert package.resources == []
    assert any("已忽略" in warning for warning in package.warnings)


async def test_preview_and_confirm(tmp_path: Path) -> None:
    store = SkillFileStore(tmp_path / "skills")
    service = SkillPackageService(store)

    preview = await service.preview(_zip({"demo/SKILL.md": SKILL_MD}), filename="demo.zip")

    assert preview.token
    assert preview.package.suggested_skill_id == "demo"

    record = await service.confirm(preview.token)

    assert record.skill_id == "demo"
    assert record.name == "示例技能"
    skill_dir = store.root / "demo"
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / ".skill-state.json").is_file()
    # 内部状态不写进 SKILL.md
    assert ".skill-state" not in (skill_dir / "SKILL.md").read_text(encoding="utf-8")

    # token 一次性
    with pytest.raises(SkillImportExpiredError):
        await service.confirm(preview.token)


async def test_confirm_expired_token(tmp_path: Path) -> None:
    service = SkillPackageService(SkillFileStore(tmp_path / "skills"), ttl_seconds=0.001)
    preview = await service.preview(_zip({"demo/SKILL.md": SKILL_MD}))

    import asyncio

    await asyncio.sleep(0.01)

    with pytest.raises(SkillImportExpiredError):
        await service.confirm(preview.token)


async def test_export_round_trip(tmp_path: Path) -> None:
    store = SkillFileStore(tmp_path / "skills")
    packages = SkillPackageService(store)
    skill = await store.create_skill(
        name="导出技能",
        description="当需要导出测试时使用",
        content="你是导出技能。",
        skill_id="export-skill",
        resources=[
            SkillPackageFile(name="references/note.md", content="附件正文"),
            SkillPackageFile(name="scripts/run.py", content="print(1)\n"),
        ],
    )

    blob = await packages.export(skill.skill_id)

    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = set(archive.namelist())
    assert names == {
        "export-skill/SKILL.md",
        "export-skill/references/note.md",
        "export-skill/scripts/run.py",
    }

    # 导出的包可以再次导入，得到等价技能
    preview = await packages.preview(blob, filename="export-skill.zip")
    imported = await packages.confirm(preview.token)

    assert imported.name == skill.name
    assert imported.description == skill.description
    assert imported.content == skill.content
    resources = await store.list_resources(imported.skill_id)
    assert [item.resource_id for item in resources] == [
        "references/note.md",
        "scripts/run.py",
    ]


async def test_export_collection(tmp_path: Path) -> None:
    store = SkillFileStore(tmp_path / "skills")
    packages = SkillPackageService(store)
    await store.create_skill(
        name="技能 A",
        description="A 的适用场景",
        content="A 的指令",
        skill_id="skill-a",
    )
    await store.create_skill(
        name="技能 B",
        description="B 的适用场景",
        content="B 的指令",
        skill_id="skill-b",
    )
    records = await store.list_skills()

    blob = await packages.export_collection(records)

    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    assert {"skill-a/SKILL.md", "skill-b/SKILL.md", "manifest.json"} <= names
    assert manifest["format"] == "self-agent-skills"
    assert {item["skill_id"] for item in manifest["skills"]} == {"skill-a", "skill-b"}


async def test_export_missing_skill(tmp_path: Path) -> None:
    packages = SkillPackageService(SkillFileStore(tmp_path / "skills"))
    with pytest.raises(SkillNotFoundError):
        await packages.export("nope")
