"""任务服务。

负责组装初始状态、调用 Agent Graph、整理结果。API 层不直接接触 Graph。
"""

from __future__ import annotations

from uuid import uuid4

from app.core.agent_graph import build_graph
from app.core.logging import get_logger
from app.llm.base import LLMProvider
from app.models.state import AgentState, initial_state

logger = get_logger(__name__)


class TaskService:
    """运行一次 Agent 任务。"""

    def __init__(self, llm: LLMProvider, *, max_retries: int = 2) -> None:
        self._graph = build_graph(llm, max_retries=max_retries)

    async def run(
        self,
        query: str,
        *,
        user_preferences: dict[str, str] | None = None,
        task_id: str | None = None,
    ) -> AgentState:
        run_id = task_id or str(uuid4())
        state = initial_state(query, task_id=run_id, user_preferences=user_preferences)

        logger.info(
            "任务开始",
            extra={"task_id": run_id, "event": "task_started", "status": "running"},
        )
        final_state = await self._graph.ainvoke(state)
        logger.info(
            "任务结束",
            extra={
                "task_id": run_id,
                "event": "task_finished",
                "status": final_state.get("task_status", "unknown"),
            },
        )
        return final_state
