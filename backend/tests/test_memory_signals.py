"""长期记忆提取触发条件的单元测试（纯函数）。"""

from __future__ import annotations

import pytest

from app.memory.signals import memory_signal, should_extract_memories


@pytest.mark.parametrize(
    "query",
    [
        "记住：以后回答都用中文",
        "以后都先给结论再展开",
        "我的研究方向是 RAG 与知识图谱",
        "我习惯用 Markdown 输出",
        "请记住我从事后端开发",
        "每次都用简洁的风格",
        "我负责的项目是个人知识库 Agent",
    ],
)
def test_explicit_long_term_signal_is_detected(query: str) -> None:
    assert memory_signal(query) is not None
    assert should_extract_memories(query, mode="brief") is True


@pytest.mark.parametrize(
    "query",
    [
        "用一句话说明什么是 RAG",
        "帮我总结这篇文档",
        "根据我的资料写一篇综述",
        "我是不是应该先检索再回答",
        "输出你好",
        "对比我资料中的多种方案",
    ],
)
def test_ordinary_task_has_no_signal(query: str) -> None:
    assert memory_signal(query) is None
    assert should_extract_memories(query, mode="brief") is False


def test_longform_always_extracts() -> None:
    assert should_extract_memories("写一篇 RAG 综述", mode="longform") is True


def test_verbatim_never_extracts() -> None:
    assert should_extract_memories("记住输出原文", mode="verbatim", output_mode="verbatim") is False


def test_signal_returns_matched_marker_for_display() -> None:
    assert memory_signal("记住：以后回答都用中文") == "记住"
