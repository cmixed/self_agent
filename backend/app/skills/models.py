"""技能文件存储使用的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillRecord:
    """一个 Agent 可调用的技能（结构化指令模块）。"""

    skill_id: str
    name: str
    description: str
    content: str
    enabled: bool
    builtin: bool
    created_at: str
    updated_at: str
    # 由文档生成 / 技能包导入时的来源文件名（手写/内置为 None）
    source_filename: str | None = None


@dataclass(frozen=True)
class SkillResourceRecord:
    """技能的按需附件（L3）：正文只在模型请求时进入提示词。

    ``resource_id`` 与 ``name`` 都是相对技能根目录的 POSIX 路径，
    例如 ``references/background.md``；脚本放在 ``scripts/`` 下但永不执行。
    """

    resource_id: str
    skill_id: str
    name: str
    content: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class SkillPackageFile:
    """技能包中的一个文本附件。"""

    name: str
    content: str


@dataclass(frozen=True)
class SkillPackage:
    """解析后的技能包（尚未落盘）。"""

    name: str
    description: str
    content: str
    resources: list[SkillPackageFile] = field(default_factory=list)
    # 技能包顶层目录名（合法时可作为 skill_id）
    suggested_skill_id: str | None = None
    source_filename: str | None = None
    warnings: list[str] = field(default_factory=list)
    # 保留 frontmatter 中的其它字段，导出时原样写回。
    extra: dict[str, Any] = field(default_factory=dict)
