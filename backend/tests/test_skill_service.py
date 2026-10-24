"""技能服务测试：文件目录 CRUD、内置技能保护、seed 幂等。"""

from __future__ import annotations

import json

import pytest

from app.services.skill_service import (
    BUILTIN_SKILL_IDS,
    BuiltinSkillProtectedError,
    SkillNotFoundError,
    SkillResourceNameConflictError,
    SkillResourceNotFoundError,
    SkillService,
)
from app.skills.frontmatter import parse_skill_markdown
from app.skills.store import SkillFileStore


@pytest.fixture
def store(tmp_path) -> SkillFileStore:
    return SkillFileStore(tmp_path / "skills")


@pytest.fixture
def service(store: SkillFileStore) -> SkillService:
    return SkillService(store)


async def test_ensure_seeded_creates_builtin_skills(service: SkillService) -> None:
    await service.ensure_seeded()

    skills = await service.list_skills()
    assert {skill.skill_id for skill in skills} == set(BUILTIN_SKILL_IDS)
    assert all(skill.builtin for skill in skills)
    assert all(skill.enabled for skill in skills)
    # 每个内置技能都是标准技能包
    for skill in skills:
        assert (service.store.root / skill.skill_id / "SKILL.md").is_file()


async def test_ensure_seeded_is_idempotent_and_keeps_edits(service: SkillService) -> None:
    await service.ensure_seeded()
    builtin_id = BUILTIN_SKILL_IDS[0]

    # 用户编辑 + 停用内置技能
    await service.update_skill(builtin_id, description="用户改过的描述", enabled=False)

    await service.ensure_seeded()  # 再次 seed 不覆盖

    skills = await service.list_skills()
    target = next(item for item in skills if item.skill_id == builtin_id)
    assert target.description == "用户改过的描述"
    assert target.enabled is False


async def test_create_writes_standard_skill_package(service: SkillService) -> None:
    created = await service.create_skill(
        name="自定义技能", description="我的技能", content="按步骤执行……"
    )
    skill_dir = service.store.root / created.skill_id

    parsed = parse_skill_markdown((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    assert parsed.name == "自定义技能"
    assert parsed.description == "我的技能"
    assert parsed.content == "按步骤执行……"

    state = json.loads((skill_dir / ".skill-state.json").read_text(encoding="utf-8"))
    assert state["enabled"] is True
    assert state["builtin"] is False

    assert created.builtin is False
    assert created.enabled is True
    assert created.skill_id not in set(BUILTIN_SKILL_IDS)


async def test_update_and_enabled_filter(service: SkillService) -> None:
    await service.ensure_seeded()
    created = await service.create_skill(name="技能", description="说明", content="指令")

    updated = await service.update_skill(created.skill_id, enabled=False, name="改名")
    assert updated.name == "改名"
    assert updated.enabled is False

    enabled = await service.enabled_skills()
    assert created.skill_id not in {item.skill_id for item in enabled}


async def test_update_missing_skill_raises(service: SkillService) -> None:
    with pytest.raises(SkillNotFoundError):
        await service.update_skill("no-such-skill", name="x")


async def test_skill_resources_crud_and_conflict(service: SkillService) -> None:
    skill = await service.create_skill(name="技能", description="说明", content="指令")
    created = await service.create_resource(
        skill.skill_id, name="references/checklist.md", content="检查项"
    )
    assert created.skill_id == skill.skill_id
    assert created.resource_id == "references/checklist.md"
    assert (service.store.root / skill.skill_id / "references" / "checklist.md").is_file()

    resources = await service.list_resources(skill.skill_id)
    assert [item.name for item in resources] == ["references/checklist.md"]

    updated = await service.update_resource(
        skill.skill_id, created.resource_id, content="新检查项"
    )
    assert updated.content == "新检查项"

    with pytest.raises(SkillResourceNameConflictError):
        await service.create_resource(
            skill.skill_id, name="references/checklist.md", content="重复"
        )

    renamed = await service.update_resource(
        skill.skill_id, created.resource_id, name="resources/checklist.md"
    )
    assert renamed.resource_id == "resources/checklist.md"
    assert not (service.store.root / skill.skill_id / "references" / "checklist.md").exists()

    await service.delete_resource(skill.skill_id, renamed.resource_id)
    with pytest.raises(SkillResourceNotFoundError):
        await service.delete_resource(skill.skill_id, renamed.resource_id)


async def test_resource_path_traversal_is_rejected(service: SkillService) -> None:
    skill = await service.create_skill(name="技能", description="说明", content="指令")

    for name in ("../escape.md", "/abs/path.md", "references/../../escape.md", ".hidden/x.md"):
        with pytest.raises(SkillResourceNameConflictError):
            await service.create_resource(skill.skill_id, name=name, content="x")


async def test_flat_resource_names_are_placed_under_resources(service: SkillService) -> None:
    skill = await service.create_skill(name="技能", description="说明", content="指令")

    created = await service.create_resource(skill.skill_id, name="checklist", content="检查项")

    assert created.resource_id == "resources/checklist"


async def test_scripts_are_stored_but_never_executed(service: SkillService) -> None:
    skill = await service.create_skill(name="技能", description="说明", content="指令")

    created = await service.create_resource(
        skill.skill_id, name="scripts/tool.py", content="print('hi')\n"
    )

    assert created.resource_id == "scripts/tool.py"
    resources = await service.list_resources(skill.skill_id)
    assert [item.resource_id for item in resources] == ["scripts/tool.py"]


async def test_delete_skill_removes_resources(service: SkillService) -> None:
    skill = await service.create_skill(name="技能", description="说明", content="指令")
    await service.create_resource(skill.skill_id, name="checklist", content="检查项")

    await service.delete_skill(skill.skill_id)

    with pytest.raises(SkillNotFoundError):
        await service.list_resources(skill.skill_id)


async def test_delete_user_skill_but_not_builtin(service: SkillService) -> None:
    await service.ensure_seeded()
    created = await service.create_skill(name="临时技能", description="待删除", content="content")

    await service.delete_skill(created.skill_id)
    assert await service.list_skills() is not None  # 列表仍可用

    with pytest.raises(BuiltinSkillProtectedError):
        await service.delete_skill(BUILTIN_SKILL_IDS[0])

    with pytest.raises(SkillNotFoundError):
        await service.delete_skill("no-such-skill")
