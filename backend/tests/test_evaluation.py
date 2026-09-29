from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeEmbeddingProvider

from app.evaluation.dataset import load_dataset
from app.evaluation.generation import (
    analyze_document,
    citation_metrics,
    count_chapters,
    duplicate_ratio,
    points_coverage,
    split_body_and_references,
    structure_match,
)
from app.evaluation.retrieval import score_case, summarize
from app.evaluation.runner import evaluate_retrieval


def _document(filename: str, content: str, score: float = 0.9) -> dict:
    return {
        "document_id": "d1",
        "filename": filename,
        "page": None,
        "chunk_id": f"c-{filename}-{hash(content) % 1000}",
        "content": content,
        "score": score,
    }


# --- 数据集 ---


def test_dataset_loads_and_documents_exist() -> None:
    dataset = load_dataset()

    assert len(dataset.retrieval_cases) == 7
    assert len(dataset.task_cases) == 2

    paths = dataset.document_paths()
    assert len(paths) == 3
    assert all(path.exists() for path in paths)

    filenames = {case.expected_document for case in dataset.retrieval_cases}
    assert filenames <= {path.name for path in paths}


# --- 检索指标 ---


def test_score_case_hit_and_coverage() -> None:
    case = load_dataset().retrieval_cases[0]  # rag_basics.md, ["检索", "生成"]
    retrieved = [
        _document("rag_basics.md", "RAG 先检索再生成回答"),
        _document("other.md", "无关内容"),
    ]

    score = score_case(case, retrieved)

    assert score.hit is True
    assert score.first_hit_rank == 1
    assert score.keyword_coverage == 1.0
    assert score.source_precision == pytest.approx(0.5)


def test_score_case_miss() -> None:
    case = load_dataset().retrieval_cases[0]
    score = score_case(case, [_document("other.md", "完全无关")])

    assert score.hit is False
    assert score.first_hit_rank is None
    assert score.keyword_coverage == 0.0


def test_score_case_without_results() -> None:
    case = load_dataset().retrieval_cases[0]
    score = score_case(case, [])

    assert score.hit is False
    assert score.retrieved_count == 0
    assert score.source_precision == 0.0


def test_summarize_aggregates() -> None:
    cases = load_dataset().retrieval_cases[:2]
    perfect = score_case(cases[0], [_document(cases[0].expected_document, "检索 生成 来源 幻觉")])
    missing = score_case(cases[1], [_document("other.md", "无关")])

    summary = summarize([perfect, missing])

    assert summary.cases == 2
    assert summary.hit_rate == pytest.approx(0.5)
    assert summary.mean_reciprocal_rank == pytest.approx(0.5)  # 1/1 + 0
    assert summary.mean_source_precision == pytest.approx(0.5)


def test_summarize_empty() -> None:
    summary = summarize([])
    assert summary.cases == 0
    assert summary.hit_rate == 0.0


async def test_evaluate_retrieval_end_to_end_with_fake_embeddings(tmp_path: Path) -> None:
    """用假 embedding 跑通评估流程（离线、确定性）。"""
    dataset = load_dataset()

    summary = await evaluate_retrieval(
        dataset, provider=FakeEmbeddingProvider(), top_k=5, workdir=tmp_path
    )

    assert summary.cases == len(dataset.retrieval_cases)
    assert 0.0 <= summary.hit_rate <= 1.0
    assert len(summary.scores) == len(dataset.retrieval_cases)


# --- 长文本指标 ---


def test_split_body_and_references() -> None:
    text = "# 标题\n\n## 章节\n\n正文\n\n## 参考来源\n[1] a.md"
    body, references = split_body_and_references(text)

    assert "正文" in body
    assert "参考来源" not in body
    assert references.startswith("## 参考来源")


def test_count_chapters_ignores_h1_and_references() -> None:
    text = "# 标题\n\n## 第一章\n\ntext\n\n## 第二章\n\ntext\n\n## 参考来源\n[1] x"
    body, _ = split_body_and_references(text)

    assert count_chapters(body) == 2


def test_structure_match() -> None:
    body = "## 引言\n\n## 方法"
    assert structure_match(body, ["引言", "方法"]) == 1.0
    assert structure_match(body, ["引言", "缺失章节"]) == pytest.approx(0.5)
    assert structure_match(body, []) == 0.0


def test_citation_metrics() -> None:
    body = "结论 A[1]。结论 B[2]。结论 C[9]。"
    used, validity, sources_cited = citation_metrics(body, {1, 2})

    assert used == 3
    assert validity == pytest.approx(2 / 3)
    assert sources_cited == 1.0


def test_citation_metrics_without_citations() -> None:
    assert citation_metrics("没有引用", {1}) == (0, 0.0, 0.0)


def test_duplicate_ratio_detects_repeats() -> None:
    body = "这是第一句完整的话。这是第一句完整的话。这是第二句不同的话。"
    assert duplicate_ratio(body) > 0


def test_points_coverage_is_case_insensitive() -> None:
    assert points_coverage("使用 Chunk 切分", ["chunk", "缺失"]) == pytest.approx(0.5)


def test_analyze_document_full() -> None:
    text = (
        "# 目标\n\n"
        "## 引言\n\nchunk 大小影响检索质量[1]。\n\n"
        "## 方法\n\n使用余弦相似度衡量向量距离[1]。\n\n"
        "## 参考来源\n[1] a.md"
    )
    metrics = analyze_document(
        text,
        outline=["引言", "方法"],
        source_indices={1},
        expected_points=["chunk", "相似度", "缺失要点"],
    )

    assert metrics.chapters == 2
    assert metrics.structure_match == 1.0
    assert metrics.citations_used == 1
    assert metrics.citation_validity == 1.0
    assert metrics.sources_cited == 1.0
    assert metrics.points_coverage == pytest.approx(2 / 3)
    assert metrics.length_chars == len(text)


def test_analyze_document_without_metadata() -> None:
    metrics = analyze_document("## 章节\n\n纯正文")

    assert metrics.chapters == 1
    assert metrics.structure_match == 0.0
    assert metrics.citations_used == 0
    assert metrics.citation_validity == 0.0
