"""提示词加载与渲染。

约定（AGENTS.md §10）：

- 提示词存放在 ``app/prompts/``，按**用途**命名，不按句子拆碎；
- 变量使用 ``{{var}}`` 自定义占位符，**不使用 ``str.format``**，
  避免提示词中的 JSON 大括号被当成格式字段；
- 缺失变量、多余变量、非法路径一律报错，避免静默产出坏提示词。
"""

from __future__ import annotations

import re
from functools import cache
from importlib import resources
from pathlib import PurePosixPath

# 只匹配 {{identifier}}；JSON 的 {"key": ...} 不会被误伤。
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_NAME_PART_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class PromptError(Exception):
    """提示词加载/渲染错误基类。"""


class PromptNotFoundError(PromptError):
    """提示词文件不存在。"""


class PromptFormatError(PromptError):
    """提示词名称非法，或变量与占位符不匹配。"""


def _validate_name(name: str) -> PurePosixPath:
    """校验提示词相对路径，拒绝绝对路径与路径穿越。"""
    if not name or "\\" in name or name.startswith("/") or "//" in name:
        raise PromptFormatError(f"非法提示词名称：{name!r}")

    path = PurePosixPath(name)
    parts = path.parts
    if (
        path.suffix != ".md"
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or any(not _NAME_PART_RE.fullmatch(part) for part in parts[:-1])
        or not _NAME_PART_RE.fullmatch(parts[-1].removesuffix(".md"))
    ):
        raise PromptFormatError(f"非法提示词名称：{name!r}")
    return path


@cache
def load_prompt(name: str) -> str:
    """读取提示词原文（按名称缓存）。

    名称相对 ``app/prompts/``，例如 ``planner.md`` 或 ``skills/compare.md``。
    """
    path = _validate_name(name)
    resource = resources.files("app.prompts")
    for part in path.parts:
        resource = resource.joinpath(part)
    if not resource.is_file():
        raise PromptNotFoundError(f"提示词不存在：{name}")
    return resource.read_text(encoding="utf-8")


def prompt_variables(name: str) -> frozenset[str]:
    """返回提示词中声明的变量名集合。"""
    return frozenset(_PLACEHOLDER_RE.findall(load_prompt(name)))


def render_prompt(name: str, /, **variables: object) -> str:
    """渲染提示词中的 ``{{var}}`` 占位符。

    ``variables`` 必须与模板占位符**完全一致**：缺失或多余都视为调用错误，
    避免参数拼错后悄悄把旧值/空值发给模型。
    """
    template = load_prompt(name)
    used = set(_PLACEHOLDER_RE.findall(template))
    provided = set(variables)
    missing = sorted(used - provided)
    extra = sorted(provided - used)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"缺少变量：{', '.join(missing)}")
        if extra:
            details.append(f"多余变量：{', '.join(extra)}")
        raise PromptFormatError(f"渲染 {name} 失败（{'；'.join(details)}）")

    return _PLACEHOLDER_RE.sub(lambda match: str(variables[match.group(1)]), template)
