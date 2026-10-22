"""任务级的「思考模式」开关。

为什么用 ContextVar 而不是改 ``LLMProvider.chat`` 签名：

- 思考开关是**任务级**策略（轻量路径关闭，长文保持 Provider 默认），
  不是每次补全都要传的业务参数；
- Provider 接口被大量测试替身实现，增加必填/可选参数会扩散到所有替身；
- ContextVar 在同一次 async 任务链中自动传播，节点内进入作用域即可。

Provider 侧只需在构造请求体时读取 :func:`thinking_override`：
``False`` 表示本次任务要求关闭思考；``None`` 表示沿用 Provider 默认。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_OVERRIDE: ContextVar[bool | None] = ContextVar("thinking_override", default=None)


def thinking_override() -> bool | None:
    """当前任务的思考模式覆盖值（None = 使用 Provider 默认）。"""
    return _OVERRIDE.get()


@contextmanager
def thinking_scope(enabled: bool | None) -> Iterator[None]:
    """在作用域内覆盖思考模式开关。"""
    token = _OVERRIDE.set(enabled)
    try:
        yield
    finally:
        _OVERRIDE.reset(token)
