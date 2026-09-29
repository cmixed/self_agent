"""Writer 节点。

Phase 2：依据计划一次性生成草稿（分章节生成在 Phase 4 配合 outline/validator 实现，
见 AGENTS.md §15）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.state import AgentState, StepResult
from app.rag.tools import format_context

logger = get_logger(__name__)

_WRITER_SYSTEM_PROMPT = """你是一个中文写作助手。请依据给定的计划完成用户的写作任务。

要求：
1. 直接输出正文内容，不要输出 JSON，也不要复述计划本身。
2. 结构清晰，可使用 Markdown 标题与段落。
3. 如果提供了「检索到的资料」，请优先依据这些资料作答，并用 [编号] 标注引用，
   例如：RAG 通过向量检索增强生成能力[1]。并在正文结尾给出「参考来源」列表，
   逐条列出用到的资料编号。
4. 如果未提供资料，请只依据通用知识作答，并说明未引用用户资料。
"""


def _render_writer_input(state: AgentState) -> str:
    plan = state.get("plan")
    lines = [f"用户任务：{state.get('user_query', '')}"]
    if plan:
        lines.append(f"任务目标：{plan.get('goal', '')}")
        steps = plan.get("steps") or []
        if steps:
            rendered = "\n".join(
                f"- [{step.get('type')}] {step.get('description')}" for step in steps
            )
            lines.append(f"计划步骤：\n{rendered}")

    documents = state.get("retrieved_documents") or []
    if documents:
        lines.append(
            "检索到的资料（请用 [编号] 引用，并在结尾给出「参考来源」列表）：\n"
            + format_context(documents)
        )
    elif plan and plan.get("needs_retrieval"):
        lines.append(
            "注意：本任务需要检索用户资料，但知识库中没有检索到相关内容。"
            "请只依据通用知识作答，并明确说明未引用用户资料。"
        )

    preferences = state.get("user_preferences") or {}
    if preferences:
        rendered = "；".join(f"{key}={value}" for key, value in preferences.items())
        lines.append(f"用户偏好：{rendered}")
    return "\n".join(lines)


def make_writer_node(llm: LLMProvider) -> Callable[[AgentState], Awaitable[dict]]:
    """构造绑定了 LLM 的 writer 节点。"""

    async def writer_node(state: AgentState) -> dict:
        messages = [
            ChatMessage(role="system", content=_WRITER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=_render_writer_input(state)),
        ]
        response = await llm.chat(messages, temperature=0.7)

        logger.info(
            "writer 完成",
            extra={
                "task_id": state.get("task_id"),
                "node": "writer",
                "event": "writer_completed",
                "status": "ok",
            },
        )
        return {
            "draft": response.content,
            "current_step": "write",
            "task_status": "writing",
            "messages": [ChatMessage(role="assistant", content="[writer] 草稿已生成")],
            "step_results": [
                StepResult(step_id="write", status="ok", summary="已依据计划生成草稿")
            ],
        }

    return writer_node
