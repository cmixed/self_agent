"""长文本与结构指标（AGENTS.md §23）。

全部为启发式离线计算（不需要 LLM），可用于对比不同流程的输出：
结构匹配、引用有效性、来源引用率、重复率、篇幅、要点覆盖。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_REFERENCES_HEADING = "## 参考来源"
_CHAPTER_PATTERN = re.compile(r"^## (?!#)\s*(.+?)\s*$", re.MULTILINE)
_CITATION_PATTERN = re.compile(r"\[(\d+)\]")
_SENTENCE_PATTERN = re.compile(r"[。！？!?\n]+")

_MIN_SENTENCE_CHARS = 8


@dataclass(frozen=True)
class GenerationMetrics:
    length_chars: int
    chapters: int
    structure_match: float
    citations_used: int
    citation_validity: float
    sources_cited: float
    duplicate_ratio: float
    points_coverage: float


def split_body_and_references(text: str) -> tuple[str, str]:
    """按「参考来源」小节把正文与引用列表分开。"""
    index = text.rfind(_REFERENCES_HEADING)
    if index == -1:
        return text, ""
    return text[:index], text[index:]


def count_chapters(body: str) -> int:
    return len(_CHAPTER_PATTERN.findall(body))


def structure_match(body: str, outline: list[str]) -> float:
    """大纲标题出现在正文二级标题中的比例。"""
    if not outline:
        return 0.0
    headings = {title.strip() for title in _CHAPTER_PATTERN.findall(body)}
    matched = sum(
        1
        for title in outline
        if any(title.strip() in heading or heading in title.strip() for heading in headings)
    )
    return matched / len(outline)


def citation_metrics(body: str, source_indices: set[int]) -> tuple[int, float, float]:
    """返回 (引用次数, 引用有效性, 来源被引用率)。"""
    cited = {int(match) for match in _CITATION_PATTERN.findall(body)}
    if not cited:
        return 0, 0.0, 0.0
    valid = len(cited & source_indices)
    return (
        len(cited),
        valid / len(cited),
        len(cited & source_indices) / len(source_indices) if source_indices else 0.0,
    )


def duplicate_ratio(body: str) -> float:
    """重复句子比例（1 - 去重后句子数 / 总句子数）。"""
    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_PATTERN.split(body)
        if len(sentence.strip()) >= _MIN_SENTENCE_CHARS
    ]
    if not sentences:
        return 0.0
    return 1.0 - len(set(sentences)) / len(sentences)


def points_coverage(text: str, expected_points: list[str]) -> float:
    """期望要点在文本中的覆盖率（大小写不敏感）。"""
    if not expected_points:
        return 0.0
    lowered = text.lower()
    covered = sum(1 for point in expected_points if point and point.lower() in lowered)
    return covered / len(expected_points)


def analyze_document(
    text: str,
    *,
    outline: list[str] | None = None,
    source_indices: set[int] | None = None,
    expected_points: list[str] | None = None,
) -> GenerationMetrics:
    """计算一篇长文的结构与质量指标。"""
    body, _references = split_body_and_references(text)
    indices = source_indices or set()
    citations, validity, sources_cited = citation_metrics(body, indices)

    return GenerationMetrics(
        length_chars=len(text),
        chapters=count_chapters(body),
        structure_match=structure_match(body, outline or []),
        citations_used=citations,
        citation_validity=validity,
        sources_cited=sources_cited,
        duplicate_ratio=duplicate_ratio(body),
        points_coverage=points_coverage(text, expected_points or []),
    )
