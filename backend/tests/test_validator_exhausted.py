"""章节重试耗尽后必须放行：不能反复重校验同一章直到触发递归上限。

回归背景：本地/自定义模型更容易连续产出引用越界的章节。此前 resolve_scope
会把「最后写入且已耗尽重试」的章节再次判为需要校验，导致
validator → validator 空转，最终以 graph_recursion_limit 结束任务
（而不是按 §16「重试耗尽后只报告」收尾）。
"""

from __future__ import annotations

from fakes import FakeEmbeddingProvider, ScriptedProvider
from langchain_core.runnables.config import RunnableConfig

from app.core.agent_graph import build_graph, recursion_limit
from app.models.state import initial_state
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.rag.tools import RagTool

PLAN_JSON = (
    '{"goal": "写综述", "needs_retrieval": true, "steps": ['
    '{"id": "write", "type": "writing", "description": "写正文"}]}'
)
OUTLINE_JSON = '{"sections": [{"title": "第一章"}, {"title": "第二章"}]}'
VALIDATION_FAIL = '{"passed": false, "issues": ["引用越界"], "suggested_action": "retry_writer"}'
# 正文引用 [9] 而只有 1 个来源 → 确定性预检查判该章引用越界（无需 LLM）
CHAPTER_BAD = "本章内容引用了不存在的来源。[9]"
CHAPTER_OK = "本章内容引用了来源。[1]"


def scripted() -> ScriptedProvider:
    return ScriptedProvider(
        [PLAN_JSON, OUTLINE_JSON],
        default_text=CHAPTER_BAD,
        default_json=VALIDATION_FAIL,
    )


async def _run(tmp_path, *, max_retries: int, budget: int = 6):
    store = ChromaStore(
        persist_dir=tmp_path / "chroma",
        collection_name="exhaust_kb",
        embedding_signature=FakeEmbeddingProvider().signature(),
    )
    from app.services.document_service import DocumentService

    service = DocumentService(
        provider_factory=lambda: FakeEmbeddingProvider(),
        store=store,
        documents_dir=tmp_path / "documents",
        chunk_size=200,
        chunk_overlap=20,
    )
    await service.ingest(filename="a.md", content="RAG 使用向量检索增强生成能力。".encode())

    provider = scripted()
    graph = build_graph(
        provider,
        rag_tool_provider=lambda: RagTool(Retriever(FakeEmbeddingProvider(), store, top_k=3)),
        max_retries=max_retries,
        max_sections=3,
    )
    config: RunnableConfig = {
        "configurable": {"thread_id": f"exhaust-{max_retries}"},
        "recursion_limit": recursion_limit(max_retries, max_sections=3),
    }
    state = initial_state("写综述", task_id="exhaust")
    final = await graph.ainvoke(state, config)
    return final, provider


async def test_exhausted_chapter_is_released_not_relooped(tmp_path) -> None:
    final, provider = await _run(tmp_path, max_retries=1)

    # 关键：任务正常走完，而不是撞递归上限
    assert final.get("task_status") != "error"
    assert final.get("final_answer"), "应产出最终文档（含 ⚠️ 标记）"
    assert "⚠️" in final.get("final_answer", "")

    # 重试是有限的：不会对同一章无限调用模型
    # 1 次规划 + 1 次大纲 + 每章撰写/校验若干次 + 整篇校验 + 汇总
    assert len(provider.calls) < 20, f"调用次数异常，疑似空转：{len(provider.calls)}"

    # 失败章节被如实记录
    assert final.get("failed_chapters") or any(
        not (result or {}).get("passed")
        for result in (final.get("chapter_validations") or {}).values()
    )


async def test_exhausted_chapter_then_other_chapters_still_written(tmp_path) -> None:
    """一章耗尽不应阻止后续章节：第二章仍应写入正文。"""
    final, _ = await _run(tmp_path, max_retries=1)
    sections = final.get("sections") or []
    assert len(sections) >= 2
    assert (sections[1].get("content") or "").strip(), "第二章应被继续撰写"


# 整篇校验定位到「已耗尽重试」的章节 → 必须报告后收尾（真实本地模型触发的第二条循环路径）
DOC_LOCATED_FAIL = (
    '{"passed": false, "issues": ["定位到第 1 章引用越界"], '
    '"suggested_action": "retry_writer", "chapter": 1}'
)


async def _run_with_document_located_failure(tmp_path, *, max_retries: int):
    from app.services.document_service import DocumentService

    store = ChromaStore(
        persist_dir=tmp_path / "chroma",
        collection_name="exhaust_doc_kb",
        embedding_signature=FakeEmbeddingProvider().signature(),
    )
    service = DocumentService(
        provider_factory=lambda: FakeEmbeddingProvider(),
        store=store,
        documents_dir=tmp_path / "documents",
        chunk_size=200,
        chunk_overlap=20,
    )
    await service.ingest(filename="a.md", content="RAG 使用向量检索增强生成能力。".encode())

    provider = ScriptedProvider(
        [PLAN_JSON, OUTLINE_JSON, DOC_LOCATED_FAIL],
        default_text=CHAPTER_BAD,
        default_json=DOC_LOCATED_FAIL,
    )
    graph = build_graph(
        provider,
        rag_tool_provider=lambda: RagTool(Retriever(FakeEmbeddingProvider(), store, top_k=3)),
        max_retries=max_retries,
        max_sections=3,
    )
    config: RunnableConfig = {
        "configurable": {"thread_id": f"doc-located-{max_retries}"},
        "recursion_limit": recursion_limit(max_retries, max_sections=3),
    }
    final = await graph.ainvoke(initial_state("写综述", task_id="doc-located"), config)
    return final, provider


async def test_document_validation_locating_exhausted_chapter_finishes(tmp_path) -> None:
    """整篇校验把问题定位到已耗尽的章节时，不能再回到 validator 空转。

    真实场景（本地小模型）：三章都引用越界、章级重试耗尽，
    整篇校验又给出 retry_writer + chapter=1；此时既不该重写（已无额度），
    也不该回 validator，而应「报告后收尾」。
    """
    final, provider = await _run_with_document_located_failure(tmp_path, max_retries=1)

    assert final.get("task_status") != "error", "不应以递归上限结束"
    assert final.get("final_answer"), "应产出最终文档（含 ⚠️ 标记）"
    assert "⚠️" in final.get("final_answer", "")
    assert len(provider.calls) < 20, f"调用次数异常，疑似空转：{len(provider.calls)}"
