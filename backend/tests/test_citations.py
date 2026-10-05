"""引用编号一致性：确定性检查 + Validator 预检查（必须章级、不得升级为 replan）。"""

from __future__ import annotations

import json

from fakes import ScriptedProvider

from app.agents.citations import (
    dangling_citation_indices,
    extract_citation_indices,
    find_chapters_with_dangling,
)
from app.agents.validator import make_validator_node
from app.models.state import RetrievedDocument, initial_state
from app.rag.tools import dedupe_documents, format_context, render_references

PASS = json.dumps(
    {"passed": True, "issues": [], "suggested_action": "continue"}, ensure_ascii=False
)


def _document(chunk_id: str, filename: str = "a.md") -> RetrievedDocument:
    return RetrievedDocument(
        document_id="d1", filename=filename, page=None, chunk_id=chunk_id, content="内容", score=0.9
    )


# --- 编号统一 ---


def test_numbering_is_identical_across_context_and_references() -> None:
    """重复 chunk 时，作家看到的编号与「参考来源」必须一致。"""
    documents = [_document("c1"), _document("c2"), _document("c1"), _document("c3")]

    assert [d["chunk_id"] for d in dedupe_documents(documents)] == ["c1", "c2", "c3"]
    context = format_context(documents)
    references = render_references(documents)
    assert "[3] 来源：a.md" in context  # 去重后第 3 条是 c3，而不是被跳过的重复项
    assert "[3] a.md" in references
    assert "[4]" not in context and "[4]" not in references


# --- 提取与判定 ---


def test_extract_ignores_links_and_code() -> None:
    text = "见 [1] 与 [2](https://x.com)，代码 `[99]`，围栏：\n```\n[88]\n```\n"
    # [2](url) 是 Markdown 链接、`[99]`/围栏内是代码：都不算引用
    assert extract_citation_indices(text) == [1]


def test_dangling_detects_out_of_range() -> None:
    text = "资料 [1]—[10] 均标注来源，另见 [3] 与 [12]"
    assert dangling_citation_indices(text, source_count=5) == [10, 12]
    assert dangling_citation_indices(text, source_count=12) == []


def test_dangling_when_no_sources() -> None:
    assert dangling_citation_indices("依据 [1] 的结论", source_count=0) == [1]


def test_find_chapters_with_dangling_locates_chapters() -> None:
    sections = [
        {"title": "一", "content": "正常 [1]"},
        {"title": "二", "content": "越界 [7]"},
        {"title": "三", "content": "也越界 [9]"},
    ]
    assert find_chapters_with_dangling(sections, source_count=5) == [1, 2]


# --- Validator 预检查 ---


def _state_with_chapters(contents: list[str], *, sources: int = 5) -> dict:
    state = initial_state("写综述", task_id="t-cite")
    state["outline"] = [{"title": f"第{i}章", "content": ""} for i in range(len(contents))]
    state["sections"] = [
        {"title": f"第{i}章", "content": content} for i, content in enumerate(contents)
    ]
    state["retrieved_documents"] = [_document(f"c{i}") for i in range(sources)]
    return state


async def test_chapter_precheck_skips_llm_and_uses_retry_writer() -> None:
    provider = ScriptedProvider()  # 若被调用会返回“通过”
    node = make_validator_node(provider, max_retries=2)
    state = _state_with_chapters(["正文引用 [1] 与 [9]"], sources=5)

    update = await node(state)

    result = update["validation_result"]
    assert result["passed"] is False
    assert result["suggested_action"] == "retry_writer"  # 不是 replan
    assert result["target"] == "chapter_1"
    assert "引用编号越界" in result["issues"][0]
    assert provider.calls == []  # 确定性检查命中时不调用 LLM
    assert update["retry_counts"]["chapter_1"] == 1


async def test_document_precheck_targets_offending_chapter_not_replan() -> None:
    """整篇校验发现悬空引用：定位到具体章节做章级重写，绝不升级为 replan。"""
    provider = ScriptedProvider()
    node = make_validator_node(provider, max_retries=2)
    state = _state_with_chapters(["正常 [1]", "越界 [8]", "正常 [2]"], sources=5)
    # 让 resolve_scope 进入整篇校验：所有章节都已写完且已通过
    state["chapter_validations"] = {
        f"chapter_{index}": {
            "passed": True,
            "issues": [],
            "suggested_action": "continue",
            "target": f"chapter_{index}",
        }
        for index in (1, 2, 3)
    }

    update = await node(state)

    result = update["validation_result"]
    assert result["passed"] is False
    assert result["suggested_action"] == "retry_writer"
    assert result["target"] == "chapter_2"  # 定位到问题章节
    assert provider.calls == []


async def test_clean_citations_still_use_llm_validation() -> None:
    provider = ScriptedProvider([PASS])
    node = make_validator_node(provider, max_retries=2)
    state = _state_with_chapters(["正文引用 [1] 与 [5]"], sources=5)

    update = await node(state)

    assert provider.calls, "编号合法时应继续走 LLM 校验"
    assert update["validation_result"]["passed"] is True


async def test_precheck_ignores_links_and_code_in_chapter() -> None:
    provider = ScriptedProvider([PASS])
    node = make_validator_node(provider, max_retries=2)
    state = _state_with_chapters(["见 [9](https://example.com) 与 `[8]`"], sources=5)

    update = await node(state)

    assert provider.calls, "链接与行内代码里的编号不应被当成引用"
    assert update["validation_result"]["passed"] is True


async def test_exhausted_citation_retry_is_marked_and_skipped() -> None:
    """重试耗尽后仍只报告（不静默改文），并在摘要中说明跳过。"""
    provider = ScriptedProvider()
    node = make_validator_node(provider, max_retries=1)
    state = _state_with_chapters(["越界 [9]"], sources=5)
    state["retry_counts"] = {"chapter_1": 1}  # 已达上限

    update = await node(state)

    summary = update["step_results"][0]["summary"]
    assert "引用编号越界" in summary
    assert "已达重试上限" in summary
    assert update["validation_result"]["passed"] is False


async def test_real_case_skill_invented_numbering_becomes_chapter_retry() -> None:
    """真实回归：技能结论自造 [1]—[10]、来源只有 5 条 → 章级重写而非全篇 replan。"""
    provider = ScriptedProvider()
    node = make_validator_node(provider, max_retries=2)
    state = _state_with_chapters(
        ["本综述依据资料 [1]—[10] 展开，重点见 [2][4][7]。"], sources=5
    )

    update = await node(state)

    result = update["validation_result"]
    assert result["suggested_action"] == "retry_writer"
    assert result["target"] == "chapter_1"
    assert "超出参考资料范围 [1]-[5]" in result["issues"][0]
    assert provider.calls == []


# --- 整篇校验「定位优先」：能定位就章级重写，定位不到才 replan ---


def _document_state(contents: list[str], *, sources: int = 5) -> dict:
    """所有章节已写完且已通过 → resolve_scope 会进入整篇校验。"""
    state = _state_with_chapters(contents, sources=sources)
    state["chapter_validations"] = {
        f"chapter_{index}": {
            "passed": True,
            "issues": [],
            "suggested_action": "continue",
            "target": f"chapter_{index}",
        }
        for index in range(1, len(contents) + 1)
    }
    return state


def _validation_json(action: str, *, chapter: int | None = None, issues=None) -> str:
    return json.dumps(
        {
            "passed": False,
            "issues": issues or ["第二章内容重复冗余"],
            "suggested_action": action,
            "chapter": chapter,
        },
        ensure_ascii=False,
    )


async def test_document_retry_writer_with_chapter_rewrites_only_that_chapter() -> None:
    """整篇问题能定位到章节 → 章级重写（不再全文 replan）。"""
    provider = ScriptedProvider([_validation_json("retry_writer", chapter=2)])
    node = make_validator_node(provider, max_retries=2)
    state = _document_state(["第一章内容 [1]", "第二章内容 [2]", "第三章内容 [3]"])

    update = await node(state)

    result = update["validation_result"]
    assert result["suggested_action"] == "retry_writer"
    assert result["target"] == "chapter_2"
    assert update["retry_counts"] == {"chapter_2": 1}
    assert "[整篇校验定位到 chapter_2]" in update["step_results"][0]["summary"]


async def test_document_retry_writer_without_chapter_still_replans() -> None:
    """定位不到章节（计划/结构问题）→ 维持原有 replan 行为。"""
    provider = ScriptedProvider([_validation_json("retry_writer")])
    node = make_validator_node(provider, max_retries=2)
    state = _document_state(["第一章内容 [1]", "第二章内容 [2]"])

    update = await node(state)

    result = update["validation_result"]
    assert result["suggested_action"] == "replan"
    assert result["target"] == "document"
    assert update["retry_count"] == 1


async def test_document_retry_writer_with_invalid_chapter_replans() -> None:
    """章节号越界 → 忽略定位，回退 replan（模型乱填不破坏流程）。"""
    provider = ScriptedProvider([_validation_json("retry_writer", chapter=99)])
    node = make_validator_node(provider, max_retries=2)
    state = _document_state(["第一章内容 [1]", "第二章内容 [2]"])

    update = await node(state)

    assert update["validation_result"]["suggested_action"] == "replan"
    assert update["retry_count"] == 1


async def test_document_explicit_replan_is_respected() -> None:
    """模型明确判为计划问题 → 仍然 replan。"""
    provider = ScriptedProvider([_validation_json("replan", issues=["整体跑题"])])
    node = make_validator_node(provider, max_retries=2)
    state = _document_state(["第一章内容 [1]"])

    update = await node(state)

    assert update["validation_result"]["suggested_action"] == "replan"
    assert update["validation_result"]["target"] == "document"


async def test_chapter_scope_unaffected_by_locate_rule() -> None:
    """章级校验不受影响：仍是在该章上重写。"""
    provider = ScriptedProvider([_validation_json("retry_writer", chapter=3)])
    node = make_validator_node(provider, max_retries=2)
    state = _state_with_chapters(["第一章内容 [1]"], sources=5)  # 只有一章，scope=chapter

    update = await node(state)

    assert update["validation_result"]["target"] == "chapter_1"
    assert update["validation_result"]["suggested_action"] == "retry_writer"
