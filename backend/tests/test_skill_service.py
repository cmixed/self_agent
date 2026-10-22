"""技能服务测试：CRUD、内置技能保护、seed 幂等。"""

from __future__ import annotations

import pytest

from app.memory.sqlite import SqliteDatabase
from app.services.skill_service import (
    BUILTIN_SKILLS,
    BuiltinSkillProtectedError,
    SkillNotFoundError,
    SkillResourceNameConflictError,
    SkillResourceNotFoundError,
    SkillService,
)


@pytest.fixture
def service(tmp_path) -> SkillService:
    database = SqliteDatabase(tmp_path / "app.db")
    database.initialize()
    return SkillService(database)


async def test_ensure_seeded_creates_builtin_skills(service: SkillService) -> None:
    await service.ensure_seeded()

    skills = await service.list_skills()
    assert {skill.skill_id for skill in skills} == {seed["skill_id"] for seed in BUILTIN_SKILLS}
    assert all(skill.builtin for skill in skills)
    assert all(skill.enabled for skill in skills)


async def test_ensure_seeded_is_idempotent_and_keeps_edits(service: SkillService) -> None:
    await service.ensure_seeded()
    builtin_id = BUILTIN_SKILLS[0]["skill_id"]

    # 用户编辑 + 停用内置技能
    await service.update_skill(builtin_id, description="用户改过的描述", enabled=False)

    await service.ensure_seeded()  # 再次 seed 不覆盖

    skill = await service.list_skills()
    target = next(item for item in skill if item.skill_id == builtin_id)
    assert target.description == "用户改过的描述"
    assert target.enabled is False


async def test_create_and_update_and_list(service: SkillService) -> None:
    await service.ensure_seeded()

    created = await service.create_skill(
        name="自定义技能", description="我的技能", content="按步骤执行……"
    )
    assert created.builtin is False
    assert created.enabled is True
    assert created.skill_id not in {seed["skill_id"] for seed in BUILTIN_SKILLS}

    updated = await service.update_skill(created.skill_id, enabled=False, name="改名")
    assert updated is not None
    assert updated.name == "改名"
    assert updated.enabled is False

    # 技能目录只包含启用中的技能
    enabled = await service.enabled_skills()
    assert created.skill_id not in {item.skill_id for item in enabled}


async def test_update_missing_skill_raises(service: SkillService) -> None:
    with pytest.raises(SkillNotFoundError):
        await service.update_skill("no-such-skill", name="x")


async def test_skill_resources_crud_and_conflict(service: SkillService) -> None:
    skill = await service.create_skill(name="技能", description="说明", content="指令")
    created = await service.create_resource(skill.skill_id, name="checklist", content="检查项")
    assert created.skill_id == skill.skill_id

    resources = await service.list_resources(skill.skill_id)
    assert [item.name for item in resources] == ["checklist"]

    updated = await service.update_resource(skill.skill_id, created.resource_id, content="新检查项")
    assert updated.content == "新检查项"

    with pytest.raises(SkillResourceNameConflictError):
        await service.create_resource(skill.skill_id, name="checklist", content="重复")

    await service.delete_resource(skill.skill_id, created.resource_id)
    with pytest.raises(SkillResourceNotFoundError):
        await service.delete_resource(skill.skill_id, created.resource_id)


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
        await service.delete_skill(BUILTIN_SKILLS[0]["skill_id"])

    with pytest.raises(SkillNotFoundError):
        await service.delete_skill("no-such-skill")
