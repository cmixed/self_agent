"""评估执行逻辑。

检索评估与对比实验都使用**临时向量库**，避免污染用户的个人知识库。
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.embedding.base import EmbeddingProvider
from app.evaluation.dataset import EvaluationDataset
from app.evaluation.retrieval import RetrievalSummary, score_case, summarize
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.rag.tools import RagTool
from app.services.document_service import DocumentService


@dataclass(frozen=True)
class EvaluationKnowledgeBase:
    store: ChromaStore
    retriever: Retriever
    tool: RagTool


async def build_evaluation_kb(
    dataset: EvaluationDataset,
    *,
    provider: EmbeddingProvider,
    top_k: int = 5,
    workdir: Path | None = None,
) -> EvaluationKnowledgeBase:
    """把数据集语料导入临时向量库，返回检索器与 RAG Tool。"""
    directory = Path(workdir) if workdir is not None else Path(tempfile.mkdtemp(prefix="eval-"))
    store = ChromaStore(
        persist_dir=directory / "chroma",
        collection_name="evaluation_kb",
        embedding_signature=provider.signature(),
    )
    service = DocumentService(
        provider_factory=lambda: provider,
        store=store,
        documents_dir=directory / "documents",
    )

    for path in dataset.document_paths():
        await service.ingest(filename=path.name, content=path.read_bytes())

    retriever = Retriever(provider, store, top_k=top_k)
    return EvaluationKnowledgeBase(store=store, retriever=retriever, tool=RagTool(retriever))


async def evaluate_retrieval(
    dataset: EvaluationDataset,
    *,
    provider: EmbeddingProvider,
    top_k: int = 5,
    workdir: Path | None = None,
) -> RetrievalSummary:
    """在临时知识库上逐条评估检索效果。"""
    kb = await build_evaluation_kb(dataset, provider=provider, top_k=top_k, workdir=workdir)

    scores = []
    for case in dataset.retrieval_cases:
        retrieved = await kb.retriever.retrieve(case.question)
        scores.append(score_case(case, retrieved))

    return summarize(scores)
