"""``as_int``：把 AgentState 里的松散值安全转成 int（app/core/coerce.py）。"""

from __future__ import annotations

import pytest

from app.core.coerce import as_int


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (6000, 6000),
        ("6000", 6000),
        (" 6000 ", 6000),
        (5999.9, 5999),  # float 截断，不四舍五入
        (0, 0),
        (-5, -5),
    ],
)
def test_as_int_accepts_numbers_and_numeric_strings(value: object, expected: int) -> None:
    assert as_int(value) == expected


@pytest.mark.parametrize("value", [None, True, False, "abc", "", object(), [1, 2]])
def test_as_int_falls_back_to_default(value: object) -> None:
    # bool 不算数值：标志位被当成数字用通常是 bug，宁可回退到默认值
    assert as_int(value, default=900) == 900
