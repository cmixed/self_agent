"""技能文件存储（SKILL.md + 附件目录）。

技能不再存放在 SQLite 的 ``skills`` / ``skill_resources`` 表中，而是以标准
目录作为唯一内容源：

    data/skills/<skill_id>/
    ├── SKILL.md
    ├── .skill-state.json      # 应用内部状态（启用/内置/时间戳/来源）
    ├── references/
    ├── resources/
    └── scripts/                # 只保存文本，永不执行

``SKILL.md`` 的 YAML frontmatter 保存 name/description，正文保存技能指令。
"""

from app.skills.models import SkillPackage, SkillPackageFile, SkillRecord, SkillResourceRecord

__all__ = [
    "SkillPackage",
    "SkillPackageFile",
    "SkillRecord",
    "SkillResourceRecord",
]
