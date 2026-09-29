"""评估数据集加载。

数据集随代码提交（``app/evaluation/dataset/``），保证评估可复现；
评估时使用独立的临时向量库，不污染用户的个人知识库。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent / "dataset"
DOCUMENTS_DIR = DATASET_DIR / "documents"


@dataclass(frozen=True)
class RetrievalCase:
    """一条检索评估样本。"""

    id: str
    question: str
    expected_document: str
    expected_keywords: list[str]


@dataclass(frozen=True)
class TaskCase:
    """一条端到端任务评估样本。"""

    id: str
    query: str
    expected_points: list[str]
    min_chapters: int = 1


@dataclass(frozen=True)
class EvaluationDataset:
    documents_dir: Path
    retrieval_cases: list[RetrievalCase]
    task_cases: list[TaskCase]

    def document_paths(self) -> list[Path]:
        return sorted(self.documents_dir.glob("*.md")) + sorted(self.documents_dir.glob("*.txt"))


def load_dataset(dataset_dir: Path | None = None) -> EvaluationDataset:
    """加载内置数据集（也可传入自定义目录，结构相同）。"""
    root = dataset_dir or DATASET_DIR
    documents_dir = root / "documents"

    qa_payload = json.loads((root / "qa.json").read_text(encoding="utf-8"))
    task_payload = json.loads((root / "tasks.json").read_text(encoding="utf-8"))

    return EvaluationDataset(
        documents_dir=documents_dir,
        retrieval_cases=[
            RetrievalCase(
                id=item["id"],
                question=item["question"],
                expected_document=item["expected_document"],
                expected_keywords=list(item.get("expected_keywords") or []),
            )
            for item in qa_payload["cases"]
        ],
        task_cases=[
            TaskCase(
                id=item["id"],
                query=item["query"],
                expected_points=list(item.get("expected_points") or []),
                min_chapters=int(item.get("min_chapters", 1)),
            )
            for item in task_payload["tasks"]
        ],
    )
