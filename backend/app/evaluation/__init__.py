"""Agent / RAG 评估（AGENTS.md §23）。

评估模块本身不参与业务链路，只读取数据集与被测组件输出。
"""

from app.evaluation.dataset import (
    EvaluationDataset,
    RetrievalCase,
    TaskCase,
    load_dataset,
)

__all__ = [
    "EvaluationDataset",
    "RetrievalCase",
    "TaskCase",
    "load_dataset",
]
