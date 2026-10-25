"""长期记忆去重：归一化与相似度判定。

为什么需要这一层：LLM 每次长文任务后都会提取一次长期记忆，措辞会漂移
（「经常撰写技术综述」→「常写技术综述」），而 SQLite 的精确匹配
（``user_id + kind + content``）只能挡住一字不差的重复。偏好与记忆又是
两条写入通道，同一条信息可能同时落进两张表。

这里只做**确定性**判定（纯函数、无 IO），供 ``MemoryService`` 在写入前调用：

- 归一化：NFKC + casefold + 去掉空白 / 标点 / 符号；
- 文本重复：完全相等、包含关系（长度相近）、字符集合重叠系数；
- 偏好键：把常见中英文别名收敛到 ``style`` / ``format`` / ``language`` /
  ``task_types`` 四个规范键。

刻意保持保守：宁可留下一条措辞不同的记忆，也不要把「偏好中文」和
「偏好英文」这类相反信息判成重复。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

# 少于这个字数的文本不参与相似度判断（「中文」「Markdown」这类短词误判率高）
MIN_COMPARE_CHARS = 4
# 两条文本长度比低于此值视为不同粒度，不做相似度判断
MIN_LENGTH_RATIO = 0.6
# 字符集合重叠系数阈值（1.0 = 短文本的每个字都出现在长文本里）
DUPLICATE_OVERLAP = 0.85

# 规范键 -> 别名（别名本身已归一化：小写、无空白/下划线/连字符）
_PREFERENCE_KEY_ALIASES: dict[str, str] = {
    "style": "style",
    "写作风格": "style",
    "文章风格": "style",
    "风格": "style",
    "writingstyle": "style",
    "format": "format",
    "输出格式": "format",
    "格式": "format",
    "outputformat": "format",
    "language": "language",
    "语言": "language",
    "输出语言": "language",
    "lang": "language",
    "tasktypes": "task_types",
    "任务类型": "task_types",
    "常见任务类型": "task_types",
    "常用任务类型": "task_types",
}


def normalize_text(text: str) -> str:
    """归一化为比较用的紧凑文本（保留语义字符，去掉排版差异）。"""
    folded = unicodedata.normalize("NFKC", text).casefold().strip()
    return "".join(
        char for char in folded if not unicodedata.category(char).startswith(("P", "Z", "S", "C"))
    )


def canonical_preference_key(key: str) -> str:
    """把偏好的键收敛到规范写法；未知键只做归一化，保留用户原意。"""
    normalized = normalize_text(key)
    if not normalized:
        return ""
    return _PREFERENCE_KEY_ALIASES.get(normalized, normalized)


def _char_overlap(first: str, second: str) -> float:
    """字符集合重叠系数：交集 / 较短集合大小。"""
    left, right = set(first), set(second)
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def is_duplicate_text(first: str, second: str) -> bool:
    """判断两条长期记忆是否在语义上足够接近，应视为同一条。

    判定顺序（任一命中即重复）：
    1. 归一化后完全相等；
    2. 长度相近且一条包含另一条（「使用中文」⊂「使用中文写作」）；
    3. 长度比达标且字符集合重叠 ≥ ``DUPLICATE_OVERLAP``
       （「经常撰写技术综述」≈「常写技术综述」）。
    """
    left, right = normalize_text(first), normalize_text(second)
    if not left or not right:
        return False
    if left == right:
        return True

    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) < MIN_COMPARE_CHARS:
        return False
    ratio = len(shorter) / len(longer)
    if ratio < MIN_LENGTH_RATIO:
        return False
    if shorter in longer:
        return True
    return _char_overlap(left, right) >= DUPLICATE_OVERLAP


def matches_any(text: str, candidates: Iterable[str]) -> bool:
    """文本是否与候选集合中的任意一条重复。"""
    return any(is_duplicate_text(text, candidate) for candidate in candidates)


__all__ = [
    "DUPLICATE_OVERLAP",
    "MIN_COMPARE_CHARS",
    "MIN_LENGTH_RATIO",
    "canonical_preference_key",
    "is_duplicate_text",
    "matches_any",
    "normalize_text",
]
