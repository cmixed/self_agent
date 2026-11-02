"""把 ``AgentState`` 里的松散值转回具体类型。

``AgentState`` 的若干字段是 ``dict[str, object]``（如 ``task_profile``），
从 checkpoint 反序列化后静态上只能当作 ``object``。这些值在写入时确实是我们
自己放的 int，但类型检查器无从得知，直接 ``int(...)`` 会被判为不可赋值。

这里集中做一次显式收窄，避免每个调用点各写一套 try/except 或 ``type: ignore``。
"""

from __future__ import annotations


def as_int(value: object, default: int = 0) -> int:
    """尽力把 ``value`` 转成 int；无法转换时返回 ``default``。

    - ``bool`` 不算数值（``True`` 会得到 ``default``），避免把标志位当数字用；
    - ``float`` 截断取整（不会四舍五入）；
    - ``str`` 允许前后空白，形如 ``"6000"`` 的旧数据仍可用。
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default
