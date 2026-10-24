"""SKILL.md 的 YAML frontmatter 解析与渲染。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from app.skills.errors import SkillParseError

_FRONTMATTER_DELIMITER = "---"


@dataclass(frozen=True)
class ParsedSkillMarkdown:
    name: str
    description: str
    content: str
    # 保留 frontmatter 中的其它字段，避免用户手写的元数据在编辑时丢失。
    extra: dict[str, Any] = field(default_factory=dict)


def parse_skill_markdown(text: str) -> ParsedSkillMarkdown:
    """解析 ``---`` 包围的 YAML frontmatter + Markdown 正文。"""
    normalized = text.lstrip("\ufeff")
    lines = normalized.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        raise SkillParseError("SKILL.md 缺少 YAML frontmatter（文件必须以 --- 开头）")

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == _FRONTMATTER_DELIMITER:
            end = index
            break
    if end is None:
        raise SkillParseError("SKILL.md 的 YAML frontmatter 没有结束标记 ---")

    raw_frontmatter = "".join(lines[1:end])
    try:
        data = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"SKILL.md 的 YAML frontmatter 无法解析：{exc}") from exc
    if not isinstance(data, dict):
        raise SkillParseError("SKILL.md 的 frontmatter 必须是 YAML 对象")

    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    if not name:
        raise SkillParseError("SKILL.md 的 frontmatter 缺少 name")
    if not description:
        raise SkillParseError("SKILL.md 的 frontmatter 缺少 description")

    content = "".join(lines[end + 1 :]).lstrip("\r\n").rstrip()
    if not content:
        raise SkillParseError("SKILL.md 正文不能为空")

    extra = {key: value for key, value in data.items() if key not in {"name", "description"}}
    return ParsedSkillMarkdown(
        name=name,
        description=description,
        content=content,
        extra=extra,
    )


def render_skill_markdown(
    *,
    name: str,
    description: str,
    content: str,
    extra: dict[str, Any] | None = None,
) -> str:
    """渲染标准 SKILL.md（frontmatter + 正文）。"""
    data: dict[str, Any] = dict(extra or {})
    data["name"] = name
    data["description"] = description
    frontmatter = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    body = content.strip()
    return f"{_FRONTMATTER_DELIMITER}\n{frontmatter}\n{_FRONTMATTER_DELIMITER}\n\n{body}\n"
