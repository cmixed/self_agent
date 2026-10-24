"""技能存储 / 导入导出错误类型。"""

from __future__ import annotations


class SkillError(Exception):
    """技能相关错误的基类。"""


class SkillNotFoundError(SkillError):
    """技能不存在。"""


class BuiltinSkillProtectedError(SkillError):
    """内置技能受保护（不可删除）。"""


class SkillResourceNotFoundError(SkillError):
    """技能附件不存在。"""


class SkillResourceNameConflictError(SkillError):
    """同一个技能内附件路径重复。"""


class SkillNameConflictError(SkillError):
    """技能目录 ID 已存在。"""


class SkillParseError(SkillError):
    """SKILL.md 无法解析（缺少 frontmatter / name / description）。"""

    error_type = "skill_parse_failed"


class SkillPackageError(SkillError):
    """技能包（zip）无法解析或不符合目录约定。"""

    error_type = "skill_package_invalid"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SkillPackageTooLargeError(SkillPackageError):
    """技能包超过大小 / 文件数限制。"""

    error_type = "skill_package_too_large"


class SkillImportExpiredError(SkillError):
    """导入预览已过期或不存在。"""

    error_type = "skill_import_expired"
