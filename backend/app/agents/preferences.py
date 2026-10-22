"""按任务模式渲染长期偏好。

为什么需要统一入口：历史上 planner / outline / writer 各自把**全部**偏好
注入提示词，导致「只输出你好」也会被 ``format=Markdown 分级标题+编号引用``
放大成一篇长文。现在由 TaskProfile 决定作用域：

- ``direct``：不注入（用户要的是一次性直接回答）；
- ``brief``：只注入语言偏好（不改变回答结构）；
- ``longform``：注入全部（写作风格、格式、语言）。
"""

from __future__ import annotations

from app.models.state import AgentState

# brief 只允许影响“用什么语言回答”，不允许影响结构/篇幅。
_BRIEF_KEYS = {"language"}


def preferences_for(state: AgentState) -> dict[str, str]:
    """返回本次任务真正生效的偏好子集。"""
    preferences = state.get("user_preferences") or {}
    if not preferences:
        return {}

    profile = state.get("task_profile") or {}
    policy = str(profile.get("apply_preferences") or "all")
    if policy == "none":
        return {}
    if policy == "language_only":
        return {key: value for key, value in preferences.items() if key in _BRIEF_KEYS}
    return dict(preferences)


def render_preferences(state: AgentState) -> str:
    """渲染为提示词片段；没有生效偏好时返回空字符串。"""
    preferences = preferences_for(state)
    if not preferences:
        return ""
    rendered = "；".join(f"{key}={value}" for key, value in preferences.items())
    return f"用户偏好：{rendered}"
