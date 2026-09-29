"""对比实验：Agent 流程 vs 基线 RAG QA（AGENTS.md §23）。

- **Proposed**：LangGraph Agent（规划 → 检索 → 大纲 → 逐章写作 → 校验/重试 → 汇总）
- **Baseline**：检索 top-k → 单次回答

两边使用同一个临时知识库与同一底层 LLM，只比较流程差异。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.evaluation.baseline import run_baseline
from app.evaluation.dataset import EvaluationDataset, TaskCase
from app.evaluation.generation import GenerationMetrics, analyze_document
from app.llm.base import LLMProvider
from app.services.task_service import TaskService


class CountingLLM(LLMProvider):
    """统计 LLM 调用次数的装饰器（chat_structured 内部也走 chat）。"""

    name = "counting"

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.calls = 0

    async def chat(self, messages, **kwargs):  # type: ignore[override]
        self.calls += 1
        return await self._inner.chat(messages, **kwargs)

    async def aclose(self) -> None:
        return None


@dataclass(frozen=True)
class SystemRun:
    case_id: str
    system: str
    status: str
    metrics: GenerationMetrics
    llm_calls: int
    duration_seconds: float
    sources_count: int
    chapters_failed: int


@dataclass(frozen=True)
class ComparisonReport:
    agent_runs: list[SystemRun]
    baseline_runs: list[SystemRun]

    def mean(self, system: str, field: str) -> float:
        runs = [
            run
            for run in (*self.agent_runs, *self.baseline_runs)
            if run.system == system and run.status == "completed"
        ]
        if not runs:
            return 0.0
        return sum(float(getattr(run.metrics, field)) for run in runs) / len(runs)

    def mean_scalar(self, system: str, field: str) -> float:
        runs = [run for run in (*self.agent_runs, *self.baseline_runs) if run.system == system]
        if not runs:
            return 0.0
        return sum(float(getattr(run, field)) for run in runs) / len(runs)


async def evaluate_comparison(
    dataset: EvaluationDataset,
    *,
    provider: LLMProvider,
    rag_tool_provider: callable,
    task_service_factory: callable,
    top_k: int = 5,
) -> ComparisonReport:
    """在两个系统上跑同一批任务。"""
    agent_runs: list[SystemRun] = []
    baseline_runs: list[SystemRun] = []

    for case in dataset.task_cases:
        agent_runs.append(
            await _run_agent_case(
                case,
                provider=provider,
                rag_tool_provider=rag_tool_provider,
                task_service_factory=task_service_factory,
            )
        )
        baseline_runs.append(
            await _run_baseline_case(
                case, provider=provider, rag_tool_provider=rag_tool_provider, top_k=top_k
            )
        )

    return ComparisonReport(agent_runs=agent_runs, baseline_runs=baseline_runs)


async def _run_agent_case(
    case: TaskCase,
    *,
    provider: LLMProvider,
    rag_tool_provider,
    task_service_factory,
) -> SystemRun:
    counting = CountingLLM(provider)
    service: TaskService = task_service_factory(counting, rag_tool_provider)

    started = time.perf_counter()
    status = "completed"
    state: dict = {}
    try:
        state = await service.run(case.query)
    except Exception:  # noqa: BLE001 - 评估中失败要记录而不是中断整轮
        status = "failed"
    duration = time.perf_counter() - started

    answer = str(state.get("final_answer") or "")
    outline = [section.get("title", "") for section in (state.get("outline") or [])]
    sources = state.get("retrieved_documents") or []
    validation = state.get("validation_result") or {}
    failed = state.get("retry_counts") or {}

    return SystemRun(
        case_id=case.id,
        system="agent",
        status=status if answer else "failed",
        metrics=analyze_document(
            answer,
            outline=outline,
            source_indices=set(range(1, len(sources) + 1)),
            expected_points=case.expected_points,
        ),
        llm_calls=counting.calls,
        duration_seconds=duration,
        sources_count=len(sources),
        chapters_failed=len([key for key, value in failed.items() if value and not validation]),
    )


async def _run_baseline_case(
    case: TaskCase,
    *,
    provider: LLMProvider,
    rag_tool_provider,
    top_k: int,
) -> SystemRun:
    counting = CountingLLM(provider)
    result = await run_baseline(
        llm=counting, rag_tool=rag_tool_provider(), query=case.query, top_k=top_k
    )
    sources = result.documents

    return SystemRun(
        case_id=case.id,
        system="baseline",
        status="completed" if result.answer else "failed",
        metrics=analyze_document(
            result.answer,
            outline=[],
            source_indices=set(range(1, len(sources) + 1)),
            expected_points=case.expected_points,
        ),
        llm_calls=counting.calls,
        duration_seconds=result.duration_seconds,
        sources_count=len(sources),
        chapters_failed=0,
    )
