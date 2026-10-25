"""长期记忆去重规则的单元测试（纯函数，不依赖数据库 / LLM）。"""

from __future__ import annotations

import pytest

from app.memory.dedupe import (
    canonical_preference_key,
    is_duplicate_text,
    matches_any,
    normalize_text,
)


def test_normalize_text_ignores_case_width_and_punctuation() -> None:
    assert normalize_text("  使用 Markdown。 ") == "使用markdown"
    assert normalize_text("ＲＡＧ　技术") == "rag技术"  # NFKC + 全角空格


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("style", "style"),
        ("Style", "style"),
        ("写作风格", "style"),
        ("文章风格", "style"),
        ("输出格式", "format"),
        ("output_format", "format"),
        ("语言", "language"),
        ("任务类型", "task_types"),
        ("常用任务类型", "task_types"),
        ("自定义键", "自定义键"),
    ],
)
def test_canonical_preference_key(raw: str, expected: str) -> None:
    assert canonical_preference_key(raw) == expected


def test_canonical_preference_key_empty_after_normalization() -> None:
    assert canonical_preference_key("  ") == ""


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("经常撰写技术综述", "常写技术综述"),
        ("偏好学术严谨", "偏好学术严谨。"),
        ("使用中文", "使用中文写作"),
        ("希望输出 Markdown", "希望输出 markdown 格式"),
        ("研究方向是 RAG", "研究方向为 RAG"),
    ],
)
def test_duplicate_detection_catches_reworded_records(first: str, second: str) -> None:
    assert is_duplicate_text(first, second) is True


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("偏好中文", "偏好英文"),
        ("使用中文回答", "使用英文回答"),
        ("RAG 技术综述", "RAG 技术报告"),
        ("使用 LangGraph", "使用 DeepSeek"),
        ("写综述", "撰写技术综述的方法与评估"),  # 粒度差异过大
        ("中文", "使用中文"),  # 过短，不参与近似判断
    ],
)
def test_duplicate_detection_keeps_distinct_records(first: str, second: str) -> None:
    assert is_duplicate_text(first, second) is False


def test_matches_any_short_circuits_on_exact_match() -> None:
    assert matches_any("中文", ["偏好英文", "中文"]) is True
    assert matches_any("中文", ["偏好英文", "偏好学术"]) is False
