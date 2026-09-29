"""评估命令行入口。

用法（在 ``backend/`` 下执行）::

    uv run python -m app.evaluation.run --suite retrieval
    uv run python -m app.evaluation.run --suite retrieval --top-k 3 \
        --output docs/evaluation-report.md

检索评估不调用大模型，可离线复现；端到端对比实验（``compare``）需要真实 LLM。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.core.logging import configure_logging
from app.embedding.factory import get_embedding_provider
from app.evaluation.dataset import load_dataset
from app.evaluation.retrieval import RetrievalSummary
from app.evaluation.runner import evaluate_retrieval

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _format_retrieval_report(summary: RetrievalSummary, *, top_k: int, documents: int) -> str:
    lines = [
        "# RAG 检索评估报告",
        "",
        f"- 数据集：`backend/app/evaluation/dataset/`"
        f"（{documents} 篇文档，{summary.cases} 条问答）",
        f"- 检索参数：top-k = {top_k}，余弦相似度",
        "- 说明：评估在临时向量库中进行，不污染个人知识库",
        "",
        "## 汇总指标",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| Hit@{top_k}（来源命中率） | {summary.hit_rate:.3f} |",
        f"| 关键词覆盖率 | {summary.mean_keyword_coverage:.3f} |",
        f"| 来源精确率 | {summary.mean_source_precision:.3f} |",
        f"| MRR（首个正确来源的平均倒数排名） | {summary.mean_reciprocal_rank:.3f} |",
        "",
        "## 明细",
        "",
        "| 用例 | 命中 | 首命中位次 | 关键词覆盖 | 来源精确率 | 召回条数 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for score in summary.scores:
        lines.append(
            f"| {score.case_id} | {'✅' if score.hit else '❌'} | "
            f"{score.first_hit_rank or '-'} | {score.keyword_coverage:.2f} | "
            f"{score.source_precision:.2f} | {score.retrieved_count} |"
        )
    lines += [
        "",
        "## 结果解读",
        "",
        "- **Hit@k** 反映「前 k 条结果中是否包含正确来源」，是 RAG 检索最关键的下限指标。",
        "- **来源精确率** 在本文数据集上偏低属于预期现象：语料只有 3 篇文档，"
        f"top-k={top_k} 会把每篇文档的片段都召回，因此期望来源最多只能占 1/3。"
        "在真实大规模知识库中该指标才有区分度。",
        "- **MRR** 对「正确来源排在第几位」敏感，适合观察排序质量而非仅看是否命中。",
        "- 本套件只使用本地 Embedding 模型与向量库，不调用大模型，因此完全离线可复现；"
        "每次运行结果应当一致（受向量库浮点实现影响可能有极小波动）。",
        "",
    ]
    return "\n".join(lines)


async def _run_retrieval(top_k: int, output: Path | None) -> RetrievalSummary:
    dataset = load_dataset()
    summary = await evaluate_retrieval(dataset, provider=get_embedding_provider(), top_k=top_k)

    report = _format_retrieval_report(summary, top_k=top_k, documents=len(dataset.document_paths()))
    print(report)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"[已写入] {output}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG / Agent 评估")
    parser.add_argument(
        "--suite",
        choices=("retrieval", "compare"),
        default="retrieval",
        help="retrieval=检索指标（离线）；compare=与基线对比（需真实 LLM）",
    )
    parser.add_argument("--top-k", type=int, default=5, dest="top_k")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="把 Markdown 报告写入指定路径（默认仅打印）",
    )
    args = parser.parse_args()

    configure_logging()

    if args.suite == "retrieval":
        asyncio.run(_run_retrieval(args.top_k, args.output))
        return

    parser.error("compare 套件需要真实 LLM，将在后续步骤提供")


if __name__ == "__main__":
    main()
