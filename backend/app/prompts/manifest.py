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
    PromptSpec(
        "outline.md",
        ("min_sections", "recommended_sections", "target_sections", "target_total_chars"),
    ),
    PromptSpec("writer.md"),
    PromptSpec("writer_continue.md", ("title", "tail")),
    PromptSpec("validator.md"),
    PromptSpec("verbatim_select.md", ("candidates",)),
    PromptSpec("answer_direct.md", ("target_chars",)),
    PromptSpec("answer_brief.md", ("target_chars",)),
    PromptSpec("answer_repair.md", ("issue",)),
    PromptSpec("memory_extract.md"),
    PromptSpec("skill_generate.md"),
    PromptSpec("skill_execute.md", ("target_chars",)),
    PromptSpec("skill_continue.md", ("tail", "target_chars")),
    PromptSpec("skill_extract_chunk.md", ("chunk_index", "chunk_total")),
    PromptSpec("skill_merge_chunks.md", ("hint",)),
    PromptSpec("skill_resource_directory.md", ("resources",)),
    PromptSpec("skill_resource_followup.md", ("name", "content")),
    PromptSpec("eval_baseline.md"),
)
