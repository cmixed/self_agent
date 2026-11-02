"""判断一次已完成任务是否值得做长期记忆提取。

长期记忆只在「有长期价值」的任务上提取，避免每个简短问答都多一次模型调用：

- ``longform``：沿用原有行为，完成后总是提取（长文任务最可能暴露偏好）；
- ``brief`` / ``direct``：只有用户**明确表达**长期偏好、自我信息或「记住」时才提取；
- 原文输出（``output_mode=verbatim``）：不提取（用户只是要一份原文）。

判定只看**用户 query**，不看模型生成的正文：生成内容里的「每次」「以后」等词
属于文章措辞，不能当作新的用户偏好，否则会在无关任务里反复触发提取。

纯函数、无 IO，便于单测。
"""

from __future__ import annotations

from app.memory.dedupe import normalize_text

# 明确的长期信号：偏好 / 自我信息 / 让系统记住。
# 刻意避开「我的资料 / 文档 / 知识库」这类知识库指代，也避开裸「我是」（会命中
# 「我是不是…」这类疑问句）。
LONG_TERM_SIGNALS: tuple[str, ...] = (
    # 明确要求记住
    "记住",
    "请记",
    # 以后 / 习惯 / 统一要求
    "以后都",
    "以后用",
    "以后统一",
    "今后都",
    "今后用",
    "每次都",
    "每次用",
    "总是用",
    "一律",
    "始终用",
    "统一用",
    "统一使用",
    "不要再",
    "别再",
    "偏好",
    "我习惯",
    "我喜欢",
    "我更喜欢",
    "我通常",
    "我一向",
    # 稳定的自我信息
    "我的研究方向",
    "我的专业",
    "我的背景",
    "我从事",
    "我的工作",
    "我的项目",
    "我是做",
    "我负责",
    "我正在研究",
    "我在研究",
    "我的目标",
)


def memory_signal(query: str) -> str | None:
    """返回 query 中命中的长期信号；没有则返回 ``None``。

    返回命中的具体短语而不是布尔值，便于日志与结果回显说明「为什么触发」。
    """
    normalized = normalize_text(query)
    if not normalized:
        return None
    for marker in LONG_TERM_SIGNALS:
        if marker in normalized:
            return marker
    return None


def should_extract_memories(
    query: str,
    *,
    mode: str | None,
    output_mode: str | None = None,
) -> bool:
    """是否应该为这次已完成任务提取长期记忆。"""
    if output_mode == "verbatim":
        return False
    if mode == "longform":
        return True
    return memory_signal(query) is not None


__all__ = ["LONG_TERM_SIGNALS", "memory_signal", "should_extract_memories"]
