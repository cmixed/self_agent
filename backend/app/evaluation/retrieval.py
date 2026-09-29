"""检索指标（AGENTS.md §23）。

全部为纯函数，便于离线复现与单元测试：
- Hit@k：前 k 条结果中是否包含期望来源；
- 关键词覆盖：期望要点在召回片段中的覆盖率；
- 来源精确率：召回片段中来自期望来源的比例。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.evaluation.dataset import RetrievalCase
from app.models.state import RetrievedDocument


@dataclass(frozen=True)
class RetrievalScore:
    case_id: str
    hit: bool
    keyword_coverage: float
    source_precision: float
    first_hit_rank: int | None
    retrieved_count: int


def score_case(case: RetrievalCase, retrieved: Sequence[RetrievedDocument]) -> RetrievalScore:
    """对单条样本打分。"""
    if not retrieved:
        return RetrievalScore(
            case_id=case.id,
            hit=False,
            keyword_coverage=0.0,
            source_precision=0.0,
            first_hit_rank=None,
            retrieved_count=0,
        )

    expected_rows = [
        index
        for index, document in enumerate(retrieved, start=1)
        if document.get("filename") == case.expected_document
    ]
    union_text = "\n".join(document.get("content", "") for document in retrieved)

    keywords = case.expected_keywords
    covered = sum(1 for keyword in keywords if keyword and keyword in union_text)

    return RetrievalScore(
        case_id=case.id,
        hit=bool(expected_rows),
        keyword_coverage=covered / len(keywords) if keywords else 0.0,
        source_precision=len(expected_rows) / len(retrieved),
        first_hit_rank=expected_rows[0] if expected_rows else None,
        retrieved_count=len(retrieved),
    )


@dataclass(frozen=True)
class RetrievalSummary:
    cases: int
    hit_rate: float
    mean_keyword_coverage: float
    mean_source_precision: float
    mean_reciprocal_rank: float
    scores: list[RetrievalScore]


def summarize(scores: Sequence[RetrievalScore]) -> RetrievalSummary:
    """汇总多条样本的结果。"""
    if not scores:
        return RetrievalSummary(0, 0.0, 0.0, 0.0, 0.0, [])

    count = len(scores)
    return RetrievalSummary(
        cases=count,
        hit_rate=sum(1 for score in scores if score.hit) / count,
        mean_keyword_coverage=sum(score.keyword_coverage for score in scores) / count,
        mean_source_precision=sum(score.source_precision for score in scores) / count,
        mean_reciprocal_rank=sum(
            1.0 / score.first_hit_rank for score in scores if score.first_hit_rank
        )
        / count,
        scores=list(scores),
    )
