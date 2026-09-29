"""检索评估的执行逻辑（离线，只需本地 Embedding 模型）。

在**临时向量库**中导入评估数据集，避免污染用户的个人知识库。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.embedding.base import EmbeddingProvider
from app.evaluation.dataset import EvaluationDataset
from app.evaluation.retrieval import RetrievalSummary, score_case, summarize
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.services.document_service import DocumentService


async def evaluate_retrieval(
    dataset: EvaluationDataset,
    *,
    provider: EmbeddingProvider,
    top_k: int = 5,
    workdir: Path | None = None,
) -> RetrievalSummary:
    """在临时知识库上逐条评估检索效果。"""
    directory = Path(workdir) if workdir is not None else Path(tempfile.mkdtemp(prefix="eval-"))
    store = ChromaStore(
        persist_dir=directory / "chroma",
        collection_name="evaluation_kb",
        embedding_signature=provider.signature(),
    )
    service = DocumentService(
        provider=provider,
        store=store,
        documents_dir=directory / "documents",
    )

    for path in dataset.document_paths():
        await service.ingest(filename=path.name, content=path.read_bytes())

    retriever = Retriever(provider, store, top_k=top_k)

    scores = []
    for case in dataset.retrieval_cases:
        retrieved = await retriever.retrieve(case.question)
        scores.append(score_case(case, retrieved))

    return summarize(scores)
