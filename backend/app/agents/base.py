"""Agent 节点的公共类型约定。

LangGraph 的节点签名要求参数**具名**（``state``，可选再带 ``config`` /
``writer`` / ``store``），而 ``collections.abc.Callable[[AgentState], ...]``
表达的是**位置参数**（positional-only）。把后者直接交给 ``graph.add_node``，
Pylance / pyright 会报：

    Argument of type "(AgentState) -> Awaitable[dict[...]]" cannot be assigned to
    parameter "action" of type "StateNode[...]"
    ...
    Missing keyword parameter "state"

所以各 ``make_*_node`` 工厂统一返回 :class:`AgentNode`：运行时仍是普通异步函数
（LangGraph 只按签名决定传几个参数），类型层面则明确「参数名是 state」。
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol

from app.models.state import AgentState


class AgentNode(Protocol):
    """只接收 ``state``、返回状态增量（部分更新）的异步节点。

    与 LangGraph ``StateNode`` 的单参数形式（``_Node``）结构兼容。
    需要 ``config`` / ``writer`` / ``store`` 的节点不在本项目使用；若将来要用，
    应为其单独声明接收对应关键字参数的类型，不要放宽这个协议。
    """

    def __call__(self, state: AgentState) -> Awaitable[dict[str, Any]]: ...
