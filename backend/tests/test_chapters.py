from __future__ import annotations

from app.agents.chapters import (
    chapter_index_from_target,
    chapter_target,
    ensure_aligned,
    failed_chapters,
    infer_chapter_from_issues,
    is_chapter_failed,
    last_written_index,
    next_pending_index,
)
from app.models.state import AgentState, Section, ValidationResult, initial_state


def _state(*, outline: int, written: list[int], retry_counts=None, validations=None) -> AgentState:
    state = initial_state("任务", task_id="t")
    state["outline"] = [{"title": f"章节{i + 1}", "content": ""} for i in range(outline)]
    state["sections"] = [
        {"title": f"章节{i + 1}", "content": (f"正文{i + 1}" if i in written else "")}
        for i in range(outline)
    ]
    state["retry_counts"] = retry_counts or {}
    state["chapter_validations"] = validations or {}
    return state


def test_chapter_target_round_trip() -> None:
    assert chapter_target(0) == "chapter_1"
    assert chapter_index_from_target("chapter_1") == 0
    assert chapter_index_from_target("chapter_5") == 4
    assert chapter_index_from_target("document") is None
    assert chapter_index_from_target("chapter_0") is None
    assert chapter_index_from_target("garbage") is None


def test_last_written_index() -> None:
    assert last_written_index([]) is None
    assert last_written_index([{"title": "a", "content": ""}]) is None
    assert last_written_index([{"title": "a", "content": "x"}, {"title": "b", "content": ""}]) == 0
    assert last_written_index([{"title": "a", "content": "x"}, {"title": "b", "content": "y"}]) == 1


def test_next_pending_index_skips_written_and_failed() -> None:
    state = _state(outline=3, written=[0])
    assert next_pending_index(state, max_retries=2) == 1

    # 第 2 章判定为永久失败 -> 跳过
    state = _state(
        outline=3,
        written=[0],
        retry_counts={"chapter_2": 2},
        validations={
            "chapter_2": {
                "passed": False,
                "issues": ["x"],
                "suggested_action": "retry_writer",
                "target": "chapter_2",
            }
        },
    )
    assert next_pending_index(state, max_retries=2) == 2


def test_next_pending_index_returns_none_when_all_done() -> None:
    state = _state(outline=2, written=[0, 1])
    assert next_pending_index(state, max_retries=2) is None


def test_is_chapter_failed_requires_exhausted_budget() -> None:
    validation: ValidationResult = {
        "passed": False,
        "issues": ["x"],
        "suggested_action": "retry_writer",
        "target": "chapter_1",
    }
    state = _state(
        outline=1,
        written=[0],
        retry_counts={"chapter_1": 1},
        validations={"chapter_1": validation},
    )
    assert is_chapter_failed(state, 0, max_retries=2) is False
    assert is_chapter_failed(state, 0, max_retries=1) is True

    # 通过后不算失败
    passed: ValidationResult = {**validation, "passed": True}
    state["chapter_validations"] = {"chapter_1": passed}
    assert is_chapter_failed(state, 0, max_retries=1) is False


def test_failed_chapters_lists_exhausted_ones() -> None:
    state = _state(
        outline=2,
        written=[0, 1],
        retry_counts={"chapter_2": 2},
        validations={
            "chapter_2": {
                "passed": False,
                "issues": ["方向不对"],
                "suggested_action": "retry_writer",
                "target": "chapter_2",
            }
        },
    )
    assert failed_chapters(state, max_retries=2) == [1]
    assert failed_chapters(state, max_retries=3) == []


def test_ensure_aligned_pads_sections() -> None:
    outline: list[Section] = [{"title": "a", "content": ""}, {"title": "b", "content": ""}]
    aligned = ensure_aligned([{"title": "a", "content": "x"}], outline)

    assert len(aligned) == 2
    assert aligned[0]["content"] == "x"
    assert aligned[1] == {"title": "b", "content": ""}


def test_infer_chapter_from_issues_parses_arabic_and_chinese() -> None:
    assert infer_chapter_from_issues(["第二章内容重复冗余"], total_sections=3) == 2
    assert infer_chapter_from_issues(["第 3 章缺少引用"], total_sections=3) == 3
    assert infer_chapter_from_issues(["第十二章与计划不符"], total_sections=12) == 12
    assert infer_chapter_from_issues(["第二十章需要删减"], total_sections=20) == 20


def test_infer_chapter_from_issues_requires_unique_valid_hit() -> None:
    # 没有章节引用（计划/结构问题）→ 不推断
    assert infer_chapter_from_issues(["整体跑题", "章节顺序不合理"], total_sections=3) is None
    # 同时提到多章 → 问题不是局部的
    assert infer_chapter_from_issues(["第一章过短", "第二章重复"], total_sections=3) is None
    # 同一章重复出现仍算唯一命中
    assert infer_chapter_from_issues(["第二章重复", "第二章需要删减"], total_sections=3) == 2
    # 越界章节号忽略
    assert infer_chapter_from_issues(["第九章不存在"], total_sections=3) is None
    # 没有章节时不做推断
    assert infer_chapter_from_issues(["第一章问题"], total_sections=0) is None
