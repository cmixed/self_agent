"""提示词资产测试：文件完整、变量渲染、路径安全。"""

from __future__ import annotations

import pytest

from app.prompts import PromptFormatError, PromptNotFoundError, load_prompt, render_prompt
from app.prompts.loader import prompt_variables
from app.prompts.manifest import BUILTIN_SKILL_PROMPTS, PROMPTS


def test_all_manifest_prompts_exist_and_are_not_empty() -> None:
    for spec in PROMPTS:
        text = load_prompt(spec.name)
        assert text.strip(), spec.name
        assert prompt_variables(spec.name) == set(spec.variables), spec.name


def test_builtin_skill_prompts_exist_and_have_no_placeholders() -> None:
    for skill_id, name in BUILTIN_SKILL_PROMPTS.items():
        text = load_prompt(name)
        assert text.strip(), skill_id
        assert "{{" not in text, name


def test_render_preserves_json_braces() -> None:
    outline = render_prompt(
        "outline.md",
        min_sections=1,
        recommended_sections=3,
        target_sections=5,
        target_total_chars=6000,
    )
    planner = render_prompt("planner.md")

    assert "最多 5 章" in outline
    assert "至少要有 1 章" in outline
    assert '{"sections": [{"title": "章节标题"}]}' in outline
    assert '{"goal": "任务目标"' in planner


def test_render_replaces_custom_placeholders() -> None:
    direct = render_prompt("answer_direct.md", target_chars=400)
    continuation = render_prompt("writer_continue.md", title="引言", tail="已写内容")

    assert "约 400 字以内" in direct
    assert "{{target_chars}}" not in direct
    assert "「引言」" in continuation
    assert "……已写内容" in continuation
    assert "{{" not in continuation


def test_missing_variable_is_rejected() -> None:
    with pytest.raises(PromptFormatError, match="缺少变量"):
        render_prompt("outline.md", target_sections=5)


def test_extra_variable_is_rejected() -> None:
    with pytest.raises(PromptFormatError, match="多余变量"):
        render_prompt("planner.md", unused="x")


@pytest.mark.parametrize(
    "name",
    [
        "../.env",
        "/etc/passwd",
        "skills/../planner.md",
        "planner.txt",
        "skills\\compare.md",
        "",
        "skills//compare.md",
    ],
)
def test_illegal_prompt_names_are_rejected(name: str) -> None:
    with pytest.raises(PromptFormatError):
        load_prompt(name)


def test_missing_prompt_raises_not_found() -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt("does_not_exist.md")
