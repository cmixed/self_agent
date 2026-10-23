"""章节相关的纯函数辅助。

被 writer / validator / summarizer / task_service 共用，避免各自实现一套判断。

约定：``sections`` 与 ``outline`` **按下标对齐**（outline 节点预填占位章节），
因此「第几章」可以直接用下标表示。

章节上限的语义边界见 :mod:`app.core.limits`：``max_sections`` 是本次任务的
生成上限（配置可调），不是安全兜底；循环边界一律以它为界，避免出现
「大纲有 N 章、只写 M 章、失败清单却按 N 章统计」这类不一致。
"""

from __future__ import annotations

import re

from app.core.limits import DEFAULT_MAX_SECTIONS
from app.models.state import AgentState, Section

# 兼容旧名：当前任务默认生成上限（真正的夹取在 config.effective_max_sections）
MAX_SECTIONS = DEFAULT_MAX_SECTIONS

# 「第二章」「第 2 章」这类问题描述里的章节引用。
_CHAPTER_REFERENCE = re.compile(r"第\s*([0-9]+|[一二三四五六七八九十]+)\s*章")

_CN_DIGITS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_chapter_number(token: str) -> int | None:
    """解析章节号：``"2"`` / ``"二"`` / ``"十二"`` / ``"二十"``。"""
    if token.isdigit():
        return int(token)
    if token == "十":
        return 10
    if "十" in token:
        tens, _, units = token.partition("十")
        tens_value = _CN_DIGITS.get(tens, 1) if tens else 1
        units_value = _CN_DIGITS.get(units, 0) if units else 0
        return tens_value * 10 + units_value
    return _CN_DIGITS.get(token)


def infer_chapter_from_issues(issues: list[str], *, total_sections: int) -> int | None:
    """从整篇校验的 issues 文本推断问题章节（1 基），推断不出返回 ``None``。

    只在**唯一命中**时返回：如果 issues 同时提到多个章节，说明问题不是局部的，
    继续按计划级问题处理；越界章节号同样忽略。这样可以避免把全局问题误判成
    局部问题（只重写一章并不能修复它）。
    """
    if total_sections <= 0:
        return None
    found: set[int] = set()
    for issue in issues:
        for token in _CHAPTER_REFERENCE.findall(issue):
            number = _parse_chapter_number(token)
            if number is not None and 1 <= number <= total_sections:
                found.add(number)
    if len(found) != 1:
        return None
    return next(iter(found))


def chapter_target(index: int) -> str:
    """0 基下标 -> 目标标识，如 ``0 -> "chapter_1"``。"""
    return f"chapter_{index + 1}"


def chapter_index_from_target(target: str) -> int | None:
    """``"chapter_2" -> 1``（0 基下标）；``"document"`` / 非法值 -> ``None``。"""
    if not target.startswith("chapter_"):
        return None
    suffix = target.removeprefix("chapter_")
    return int(suffix) - 1 if suffix.isdigit() and int(suffix) > 0 else None


def last_written_index(sections: list[Section]) -> int | None:
    """最后一个已写入正文的章节下标。"""
    for index in range(len(sections) - 1, -1, -1):
        if (sections[index].get("content") or "").strip():
            return index
    return None


def is_chapter_failed(state: AgentState, index: int, *, max_retries: int) -> bool:
    """该章节是否已达重试上限且仍未通过校验。"""
    target = chapter_target(index)
    validations = state.get("chapter_validations") or {}
    result = validations.get(target)
    if not isinstance(result, dict) or result.get("passed"):
        return False
    counts = state.get("retry_counts") or {}
    return counts.get(target, 0) >= max_retries


def next_pending_index(
    state: AgentState, *, max_retries: int, max_sections: int = MAX_SECTIONS
) -> int | None:
    """下一个还需要撰写的章节下标（跳过已写与已判定失败的章节）。

    边界为 ``max_sections``：超出该上限的章节（模型多给的）一律不写。
    """
    outline = state.get("outline") or []
    sections = state.get("sections") or []
    for index in range(min(len(outline), max_sections)):
        content = sections[index].get("content", "") if index < len(sections) else ""
        if content.strip():
            continue
        if is_chapter_failed(state, index, max_retries=max_retries):
            continue
        return index
    return None


def failed_chapters(
    state: AgentState, *, max_retries: int, max_sections: int = MAX_SECTIONS
) -> list[int]:
    """所有未通过校验且已达重试上限的章节下标。

    与 :func:`next_pending_index` 用同一 ``max_sections`` 边界：只有会被
    实际撰写/尝试的章节才可能出现在失败清单里。
    """
    outline = state.get("outline") or []
    return [
        index
        for index in range(min(len(outline), max_sections))
        if is_chapter_failed(state, index, max_retries=max_retries)
    ]


def ensure_aligned(sections: list[Section], outline: list[Section]) -> list[Section]:
    """补齐 ``sections`` 使下标与 ``outline`` 对齐。"""
    aligned = list(sections)
    for index, section in enumerate(outline):
        if index >= len(aligned):
            aligned.append(Section(title=section.get("title", ""), content=""))
    return aligned
