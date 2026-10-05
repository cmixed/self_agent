"""引用编号一致性的**确定性**检查（不依赖模型判断）。

背景：正文用 ``[n]`` 标注来源，编号来自「检索到的资料」（见
:func:`app.rag.tools.format_context`）。模型（含技能结论）有时会自造编号，
产生 ``[7]`` 而来源只有 5 条的悬空引用。

这类问题是**可机械判定**的，因此在这里用代码检查，而不是交给模型：

- 检查通过 → 由 LLM Validator 继续判断内容质量；
- 检查不通过 → 直接产出**章级** ``retry_writer``（可定位到具体章节），
  从而绕开 ``document + retry_writer → replan`` 的升级路径，避免为几个编号
  推倒整篇重写。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.models.state import Section

# 形如 [12] 的引用；行内代码与围栏代码块、Markdown 链接 [1](url) 不算引用
_CITATION_RE = re.compile(r"\[(\d{1,3})\]")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_MD_LINK_RE = re.compile(r"\[(\d{1,3})\]\([^)]*\)")
# 单个 issue 里最多列出多少个越界编号，避免刷屏
_MAX_LISTED = 8


def _strip_non_citations(text: str) -> str:
    """去掉代码块/行内代码/Markdown 链接，只留下可能的正文引用。"""
    cleaned = _FENCE_RE.sub(" ", text)
    cleaned = _INLINE_CODE_RE.sub(" ", cleaned)
    return _MD_LINK_RE.sub(" ", cleaned)


def extract_citation_indices(text: str) -> list[int]:
    """提取正文中出现的引用编号（去重升序）。"""
    if not text:
        return []
    return sorted({int(match) for match in _CITATION_RE.findall(_strip_non_citations(text))})


def dangling_citation_indices(text: str, *, source_count: int) -> list[int]:
    """越界（``n < 1`` 或 ``n > source_count``）的引用编号。"""
    return [index for index in extract_citation_indices(text) if index < 1 or index > source_count]


def citation_issue_text(indices: Sequence[int], *, source_count: int) -> str:
    """把越界编号渲染成可读的校验问题。"""
    listed = "、".join(f"[{index}]" for index in list(indices)[:_MAX_LISTED])
    if len(indices) > _MAX_LISTED:
        listed += " 等"
    if source_count <= 0:
        return (
            f"引用编号越界：正文出现 {listed} 引用，但本任务没有检索到任何资料；"
            "请去掉这些引用编号，或改为基于通用知识表述"
        )
    return (
        f"引用编号越界：{listed} 超出参考资料范围 [1]-[{source_count}]；"
        "引用编号只能来自「检索到的资料」，请改正或去掉这些编号"
    )


def find_chapters_with_dangling(
    sections: Sequence[Section], *, source_count: int
) -> list[int]:
    """返回存在悬空引用的章节下标（0 基，升序）。

    供整篇校验定位到具体章节：这样能给出章级 ``retry_writer``，
    而不是无法定位的整篇问题（后者会被升级为 replan）。
    """
    offenders: list[int] = []
    for index, section in enumerate(sections):
        content = str(section.get("content") or "")
        if dangling_citation_indices(content, source_count=source_count):
            offenders.append(index)
    return offenders
