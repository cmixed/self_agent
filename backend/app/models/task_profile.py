"""任务画像（TaskProfile）。

路由层根据用户输入与显式深度选择，决定本次任务走哪条执行路径。
它是**纯数据**：不依赖 LangGraph、不查数据库、不调用 LLM，便于单测。

三种模式（AGENTS.md 的「默认轻、显式重」原则）：

- ``direct``：问候、闲聊、明确「只输出/翻译/改写」等单次回答；
- ``brief``：默认的安全路径，单次生成，可检索知识库；
- ``longform``：明确的写作/长文任务，走 Planner → 大纲 → 分章 → 校验。

``direct`` / ``brief`` 不生成大纲、不逐章校验，避免简单任务被长文流水线放大。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.core.limits import (
    DEFAULT_MAX_SECTIONS,
    DEFAULT_TOTAL_CHARS,
    MAX_TOTAL_CHARS,
)

Mode = Literal["direct", "brief", "longform"]
ValidationPolicy = Literal["none", "citation_only", "document"]
PreferencePolicy = Literal["none", "language_only", "all"]
Depth = Literal["auto", "brief", "longform"]

# 轻量路径的篇幅软目标（字）。direct 更短，brief 允许一段完整回答。
DIRECT_TARGET_CHARS = 400
BRIEF_TARGET_CHARS = 900


@dataclass(frozen=True)
class TaskProfile:
    """一次任务的执行预算与策略。"""

    mode: Mode
    needs_retrieval: bool
    target_chars: int
    max_sections: int
    validation: ValidationPolicy
    apply_preferences: PreferencePolicy
    allow_skills: bool
    thinking: bool | None
    estimated_calls: int | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """转为可写入 ``AgentState`` / ``result_json`` 的普通字典。"""
        return asdict(self)

    @property
    def is_light(self) -> bool:
        return self.mode in {"direct", "brief"}


def resolve_profile(
    query: str,
    *,
    depth: str = "auto",
    use_skills: bool = False,
    target_total_chars: int = DEFAULT_TOTAL_CHARS,
    max_sections: int = DEFAULT_MAX_SECTIONS,
) -> TaskProfile:
    """根据输入决定任务模式（确定性规则，0 次 LLM 调用）。

    优先级（从高到低）：
    1. 显式 ``depth``（用户在选择器里指定）；
    2. 明确的字数要求（≥1500 字 → 长文；「不超过/以内」→ 简洁）；
    3. 明确的简短措辞（简短/简要/摘要/一句话/要点…）→ brief；
    4. 明确的长文措辞（综述/报告/论文/笔记/大纲/分章节…）→ longform；
    5. 只输出/翻译/改写/问候等单次指令 → direct；
    6. 其余 → brief（安全默认，绝不再自动升级为长文）。
    """
    text = (query or "").strip()
    chosen = (depth or "auto").strip().lower()

    if chosen == "brief":
        return _profile(
            "brief",
            text,
            use_skills,
            target_total_chars,
            max_sections,
            reason="用户显式选择简洁回答",
        )
    if chosen == "longform":
        return _profile(
            "longform",
            text,
            use_skills,
            target_total_chars,
            max_sections,
            reason="用户显式选择长文",
        )
    if chosen == "direct":
        return _profile(
            "direct",
            text,
            use_skills,
            target_total_chars,
            max_sections,
            reason="用户显式选择直接回答",
        )

    explicit = _explicit_length(text)
    if explicit is not None and (
        explicit >= 1500 or (_is_longform(text) and not _is_capped_length(text))
    ):
        return _profile(
            "longform",
            text,
            use_skills,
            _clamp_explicit_target(explicit),
            max_sections,
            reason=f"用户要求约 {explicit} 字",
        )
    if explicit is not None and explicit <= 1500 and _is_capped_length(text):
        return _profile(
            "brief",
            text,
            use_skills,
            target_total_chars,
            max_sections,
            reason=f"用户要求不超过约 {explicit} 字",
            target_override=min(BRIEF_TARGET_CHARS, max(120, explicit)),
        )

    if _is_brief(text):
        return _profile(
            "brief",
            text,
            use_skills,
            target_total_chars,
            max_sections,
            reason="检测到简洁/摘要类要求",
        )
    if _is_longform(text):
        return _profile(
            "longform",
            text,
            use_skills,
            target_total_chars,
            max_sections,
            reason="检测到写作/长文意图",
        )
    if _is_direct(text) and not _has_knowledge_hint(text):
        return _profile(
            "direct",
            text,
            use_skills,
            target_total_chars,
            max_sections,
            reason="检测到单次回答指令",
        )
    if _is_direct(text) and _has_knowledge_hint(text):
        return _profile(
            "brief",
            text,
            use_skills,
            target_total_chars,
            max_sections,
            reason="需要知识库依据，改用简洁检索回答",
        )
    return _profile(
        "brief",
        text,
        use_skills,
        target_total_chars,
        max_sections,
        reason="未检测到长文意图，默认简洁回答",
    )


def _clamp_explicit_target(chars: int) -> int:
    """把用户显式字数夹到系统允许的上限内。

    用户显式要求优先于配置目标；这里不再强推 ``MIN_TOTAL_CHARS``，
    否则「写 1000 字综述」会被悄悄改成 1500 字。
    """
    return max(120, min(int(chars), MAX_TOTAL_CHARS))


def _profile(
    mode: Mode,
    query: str,
    use_skills: bool,
    target_total_chars: int,
    max_sections: int,
    *,
    reason: str,
    target_override: int | None = None,
) -> TaskProfile:
    knowledge = _has_knowledge_hint(query)
    if mode == "direct":
        target = DIRECT_TARGET_CHARS
        validation: ValidationPolicy = "none"
        prefs: PreferencePolicy = "none"
        estimated: int | None = 1
    elif mode == "brief":
        target = target_override if target_override is not None else BRIEF_TARGET_CHARS
        validation = "citation_only"
        prefs = "language_only"
        estimated = 1
    else:
        target = target_total_chars
        validation = "document"
        prefs = "all"
        # 章节数由大纲动态决定，无法在路由阶段精确预估
        estimated = None

    return TaskProfile(
        mode=mode,
        needs_retrieval=knowledge,
        target_chars=max(120, int(target)),
        max_sections=max(1, int(max_sections)) if mode == "longform" else 1,
        validation=validation,
        apply_preferences=prefs,
        allow_skills=bool(use_skills) and mode == "longform",
        thinking=False if mode in {"direct", "brief"} else None,
        estimated_calls=estimated,
        reason=reason,
    )


# --- 规则实现（保持简单、可读、可单测）---

_KNOWLEDGE_RE = (
    "我的资料",
    "我的文档",
    "我的论文",
    "我的知识库",
    "我的笔记",
    "知识库",
    "上传的",
    "根据资料",
    "根据我的",
    "检索",
)

_BRIEF_WORDS = (
    "简短",
    "简要",
    "简洁",
    "概括",
    "摘要",
    "一句话",
    "简略",
    "简短说明",
)

_LONGFORM_WORDS = (
    "综述",
    "报告",
    "论文",
    "方案",
    "笔记",
    "指南",
    "手册",
    "大纲",
    "章节",
    "目录",
    "长文",
    "详细说明",
    "详细介绍",
    "详细分析",
    "分章节",
)

_DIRECT_PREFIXES = (
    "翻译",
    "改写",
    "润色",
    "重写",
)

_GREETINGS = {
    "你好",
    "您好",
    "hi",
    "hello",
    "hey",
    "谢谢",
    "多谢",
    "再见",
    "早上好",
    "晚上好",
    "在吗",
}


def _has_knowledge_hint(text: str) -> bool:
    return any(word in text for word in _KNOWLEDGE_RE)


def _explicit_length(text: str) -> int | None:
    import re

    match = re.search(r"(\d{3,5})\s*字", text)
    return int(match.group(1)) if match else None


def _is_capped_length(text: str) -> bool:
    return "不超过" in text or "以内" in text or "少于" in text


def _is_brief(text: str) -> bool:
    return any(word in text for word in _BRIEF_WORDS)


def _is_longform(text: str) -> bool:
    if any(word in text for word in _LONGFORM_WORDS):
        return True
    import re

    # 「写/生成/整理 + 文体」才是长文；单独一个「写」不构成长文意图。
    return bool(
        re.search(
            r"(写|撰写|生成|整理|输出|总结|调研).{0,24}"
            r"(文章|综述|报告|论文|方案|笔记|说明|指南|教程|分析|总结)",
            text,
        )
    )


def _is_direct(text: str) -> bool:
    lowered = text.strip().lower().rstrip("!！。,.，?？ ")
    if lowered in _GREETINGS:
        return True
    if any(word in text for word in ("只输出", "仅输出", "只回答", "仅回答", "只回复", "仅回复")):
        return True
    if any(
        word in text
        for word in ("不要解释", "不要展开", "不要分章", "直接回答", "直接说", "直接给出")
    ):
        return True
    return any(text.startswith(prefix) for prefix in _DIRECT_PREFIXES)
