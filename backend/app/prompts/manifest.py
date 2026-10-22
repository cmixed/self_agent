"""提示词清单。

集中声明当前使用的提示词与内置技能正文位置，测试据此检查文件完整性。
新增提示词时同步更新这里，避免出现「代码引用了文件但文件没进仓库」。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptSpec:
    """一个提示词文件及其占位符。"""

    name: str
    variables: tuple[str, ...] = ()


PROMPTS: tuple[PromptSpec, ...] = (
    PromptSpec("planner.md"),
    PromptSpec("outline.md", ("min_sections", "target_sections")),
    PromptSpec("writer.md"),
    PromptSpec("writer_continue.md", ("title", "tail")),
    PromptSpec("validator.md"),
    PromptSpec("answer_direct.md", ("target_chars",)),
    PromptSpec("answer_brief.md", ("target_chars",)),
    PromptSpec("answer_repair.md", ("issue",)),
    PromptSpec("memory_extract.md"),
    PromptSpec("skill_generate.md"),
    PromptSpec("eval_baseline.md"),
)

# 内置技能 id -> 正文文件（正文只在这里维护，数据库仅存用户副本）
BUILTIN_SKILL_PROMPTS: dict[str, str] = {
    "builtin-compare": "skills/compare.md",
    "builtin-takeaways": "skills/takeaways.md",
    "builtin-glossary": "skills/glossary.md",
}
