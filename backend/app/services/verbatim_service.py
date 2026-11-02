"""知识库原文输出服务。

原文输出是**确定性能力**，不是让模型重新生成一遍：

- AI 只负责选文档（候选少时用一次很小的结构化调用）；
- 系统负责读取上传时保存的原文件全文；
- 全文不进入 Planner / Writer / Validator 的上下文，也不消耗生成 token。

同一套逻辑服务两个入口：

1. 生成过程中的系统技能 ``system-verbatim``；
2. 工作台的「直接输出知识库原文」。
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMProvider
from app.models.schemas import DocumentInfo
from app.models.state import AgentState, PlanStep, RetrievedDocument, VerbatimOutput
from app.prompts import render_prompt
from app.rag.loader import DocumentLoadError
from app.rag.tools import RagTool
from app.services.document_service import DocumentService
from app.skills.system import SYSTEM_VERBATIM_SKILL_ID

logger = get_logger(__name__)

# 单篇原文的安全上限：超过时明确报错，不静默截断（原文输出的价值就在完整）。
DEFAULT_VERBATIM_MAX_CHARS = 200_000
# 自动选文档时最多交给模型的候选数量，避免把整个知识库塞进提示词。
MAX_SELECTION_CANDIDATES = 8
# 候选片段只用于判断主题，不用于生成正文。
_SELECTION_EXCERPT_CHARS = 240


class VerbatimError(Exception):
    """原文输出失败基类。"""


class VerbatimUnavailableError(VerbatimError):
    """本次任务不能使用知识库原文（例如 retrieval_mode=none）。"""


class VerbatimNoDocumentError(VerbatimError):
    """没有找到合适的原文文档。"""


class VerbatimDocumentNotFoundError(VerbatimError):
    """指定的文档不存在，或原文件缺失 / 无法解析。"""


class VerbatimDocumentTooLargeError(VerbatimError):
    """原文超过安全上限。"""

    def __init__(self, chars: int, limit: int) -> None:
        super().__init__(f"原文约 {chars} 字，超过单篇上限 {limit} 字，未自动截断")
        self.chars = chars
        self.limit = limit


@dataclass(frozen=True)
class VerbatimCandidate:
    """自动选择时的候选文档。"""

    document_id: str
    filename: str
    title: str
    hits: int = 0
    best_score: float | None = None
    excerpt: str = ""

    @property
    def rank(self) -> tuple[int, float]:
        return (self.hits, self.best_score if self.best_score is not None else 0.0)


class VerbatimChoice(BaseModel):
    """模型选文档的结构化输出。"""

    document_id: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


def _normalize_name(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(char for char in normalized if char.isalnum())


def _document_names(document: DocumentInfo) -> set[str]:
    stem = Path(document.filename).stem
    names = {
        _normalize_name(document.filename),
        _normalize_name(document.title),
        _normalize_name(stem),
    }
    return {name for name in names if len(name) >= 2}


def _explicit_matches(documents: Sequence[DocumentInfo], text: str) -> list[DocumentInfo]:
    """返回任务文本中明确提到的文档（按名称长度优先，避免短标题误伤）。"""
    normalized = _normalize_name(text)
    if not normalized:
        return []
    scored: list[tuple[int, DocumentInfo]] = []
    for document in documents:
        matched = [name for name in _document_names(document) if name in normalized]
        if matched:
            scored.append((max(len(name) for name in matched), document))
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return [document for score, document in scored if score == best]


def render_verbatim_document(output: VerbatimOutput) -> str:
    """直接输出入口的最终文档：来源说明 + 原文全文。"""
    title = output.get("title") or Path(output.get("filename", "")).stem
    filename = output.get("filename", "")
    chars = output.get("chars", 0)
    header = f"# {title}".strip() if title else ""
    note = f"> 来源：知识库 · {filename} · 逐字输出，未经过模型改写（约 {chars} 字）"
    parts = [part for part in (header, note, output.get("content", "")) if part]
    return "\n\n".join(parts).strip()


def render_verbatim_appendix(output: VerbatimOutput) -> str:
    """生成任务中未使用占位符时的附录。"""
    title = output.get("filename") or output.get("title", "")
    chars = output.get("chars", 0)
    return (
        f"## 原文：《{title}》\n\n"
        f"> 以下内容由系统从知识库逐字读取，未经过模型改写（约 {chars} 字）。\n\n"
        f"{output.get('content', '')}"
    ).strip()


def render_verbatim_notice(state: AgentState) -> str:
    """给 Writer 的原文素材说明。

    只暴露占位符、文件名和字数；正文永远不进入提示词。计划中的原文步骤描述
    会一并给出，让模型知道用户希望把原文放在哪里（仍由模型决定具体位置）。
    """
    outputs = state.get("verbatim_outputs") or []
    if not outputs:
        return ""
    lines = [
        "系统已准备知识库原文（全文不会进入提示词）：",
    ]
    for index, output in enumerate(outputs, start=1):
        lines.append(
            f"- [[VERBATIM:{index}]] 《{output.get('filename', '')}》"
            f" 约 {output.get('chars', 0)} 字"
        )
    plan = state.get("plan") or {}
    requirements = [
        str(step.get("description") or "").strip()
        for step in plan.get("steps", [])
        if step.get("type") == "skill"
        and step.get("skill_id") == SYSTEM_VERBATIM_SKILL_ID
        and str(step.get("description") or "").strip()
    ]
    if requirements:
        lines.append(f"计划中对原文的要求：{'；'.join(requirements)}")
    lines.append(
        "如果任务要求在某处完整引用原文，请在该位置**单独一行**写对应占位符；"
        "不要改写、概括、复制或补写原文内容。系统会在校验后替换为全文。"
        "如果任务不需要输出原文，请不要写占位符。"
    )
    return "\n".join(lines)


class VerbatimService:
    """选文档、读原文、构造结果。"""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        document_service_provider: Callable[[], DocumentService],
        rag_tool_provider: Callable[[], RagTool] | None = None,
        max_chars: int = DEFAULT_VERBATIM_MAX_CHARS,
    ) -> None:
        self._llm = llm
        self._document_service_provider = document_service_provider
        self._rag_tool_provider = rag_tool_provider
        self._max_chars = max(1, max_chars)

    async def resolve_for_state(
        self,
        state: AgentState,
        step: PlanStep,
    ) -> VerbatimOutput:
        """生成流程中的系统技能：从本次范围的检索结果中选一篇。"""
        scope = state.get("retrieval_scope") or None
        scope_ids = scope.get("document_ids") if scope else None
        return await self._resolve(
            query=str(state.get("user_query") or ""),
            step_description=str(step.get("description") or ""),
            scope_ids=scope_ids,
            retrieved_documents=list(state.get("retrieved_documents") or []),
            allow_retrieval=False,
        )

    async def resolve_direct(
        self,
        query: str,
        *,
        document_id: str | None = None,
        scope_ids: Sequence[str] | None = None,
        retrieval_mode: str = "all",
    ) -> VerbatimOutput:
        """工作台直接入口：可指定文档，也可自动选择最合适的一篇。"""
        if retrieval_mode == "none":
            raise VerbatimUnavailableError("本次任务设置为「不检索知识库」，无法输出原文")

        documents = await self._list_documents(scope_ids)
        if not documents:
            raise VerbatimNoDocumentError("当前检索范围内没有文档，无法输出原文")

        if document_id:
            selected = next(
                (item for item in documents if item.document_id == document_id),
                None,
            )
            if selected is None:
                raise VerbatimDocumentNotFoundError("指定的文档不在当前检索范围内")
            return await self._read_and_build(selected, selection="explicit", reason="用户指定文档")

        return await self._resolve(
            query=query,
            step_description="",
            scope_ids=scope_ids,
            retrieved_documents=[],
            allow_retrieval=True,
        )

    async def _list_documents(self, scope_ids: Sequence[str] | None) -> list[DocumentInfo]:
        documents = await self._document_service_provider().list_documents()
        if scope_ids is None:
            return documents
        allowed = set(scope_ids)
        # 空列表代表「范围内没有文档」，绝不能退化成整个知识库。
        return [item for item in documents if item.document_id in allowed]

    async def _resolve(
        self,
        *,
        query: str,
        step_description: str,
        scope_ids: Sequence[str] | None,
        retrieved_documents: Sequence[RetrievedDocument],
        allow_retrieval: bool,
    ) -> VerbatimOutput:
        documents = await self._list_documents(scope_ids)
        if not documents:
            raise VerbatimNoDocumentError("当前检索范围内没有文档，无法输出原文")

        text = f"{query}\n{step_description}".strip()
        explicit = _explicit_matches(documents, text)
        if len(explicit) == 1:
            return await self._read_and_build(
                explicit[0], selection="filename", reason="任务中明确提到了该文档"
            )

        if len(documents) == 1:
            return await self._read_and_build(
                documents[0], selection="single", reason="检索范围内只有一篇文档"
            )

        candidates = self._candidates(documents, retrieved_documents)
        if not candidates and allow_retrieval:
            candidates = await self._retrieve_candidates(query, scope_ids=scope_ids)

        if not candidates:
            raise VerbatimNoDocumentError("没有检索到与任务相关的文档，请手动选择一篇")

        if len(candidates) == 1:
            selected = candidates[0]
            return await self._read_and_build(
                self._document_by_id(documents, selected.document_id),
                selection="retrieval",
                reason="检索结果只命中一篇文档",
            )

        choice = await self._choose_with_llm(
            query=query if allow_retrieval else text,
            step_description=step_description,
            candidates=candidates,
        )
        if choice is not None:
            document = self._document_by_id(documents, choice.document_id)
            reason = choice.reason.strip() or "模型选择了与该任务最相关的一篇"
            return await self._read_and_build(
                document, selection="llm", reason=f"模型选择：{reason}"
            )

        # 模型不可用 / 输出非法时回退到检索排序，保证生成流程仍可继续。
        fallback = candidates[0]
        return await self._read_and_build(
            self._document_by_id(documents, fallback.document_id),
            selection="retrieval",
            reason="模型未给出有效选择，按检索相关度选择",
        )

    def _candidates(
        self,
        documents: Sequence[DocumentInfo],
        retrieved_documents: Sequence[RetrievedDocument],
    ) -> list[VerbatimCandidate]:
        allowed = {document.document_id for document in documents}
        by_id: dict[str, VerbatimCandidate] = {}
        for hit in retrieved_documents:
            document_id = hit.get("document_id", "")
            if document_id not in allowed:
                continue
            current = by_id.get(document_id)
            score = hit.get("score")
            content = str(hit.get("content") or "")
            if current is None:
                by_id[document_id] = VerbatimCandidate(
                    document_id=document_id,
                    filename=str(hit.get("filename") or ""),
                    title=str(hit.get("filename") or ""),
                    hits=1,
                    best_score=score,
                    excerpt=content[:_SELECTION_EXCERPT_CHARS],
                )
            else:
                by_id[document_id] = VerbatimCandidate(
                    document_id=document_id,
                    filename=current.filename,
                    title=current.title,
                    hits=current.hits + 1,
                    best_score=max(
                        current.best_score or 0.0,
                        score or 0.0,
                    ),
                    excerpt=current.excerpt,
                )
        # 补齐标题：检索 metadata 只有 filename，展示时用知识库里的 title。
        info = {document.document_id: document for document in documents}
        return sorted(
            [
                VerbatimCandidate(
                    document_id=item.document_id,
                    filename=info[item.document_id].filename,
                    title=info[item.document_id].title,
                    hits=item.hits,
                    best_score=item.best_score,
                    excerpt=item.excerpt,
                )
                for item in by_id.values()
            ],
            key=lambda item: item.rank,
            reverse=True,
        )

    async def _retrieve_candidates(
        self,
        query: str,
        *,
        scope_ids: Sequence[str] | None,
    ) -> list[VerbatimCandidate]:
        if not query.strip() or self._rag_tool_provider is None:
            return []
        try:
            hits = await self._rag_tool_provider().search(
                query, top_k=MAX_SELECTION_CANDIDATES, document_ids=scope_ids
            )
        except Exception as exc:  # 检索失败不等于原文不可用（指定文档路径不经过这里）
            logger.warning(
                "原文选择检索失败",
                extra={
                    "event": "verbatim_retrieval_failed",
                    "status": "warning",
                    "error": str(exc),
                },
            )
            return []
        documents = await self._list_documents(scope_ids)
        return self._candidates(documents, hits)

    async def _choose_with_llm(
        self,
        *,
        query: str,
        step_description: str,
        candidates: Sequence[VerbatimCandidate],
    ) -> VerbatimChoice | None:
        shortlist = list(candidates[:MAX_SELECTION_CANDIDATES])
        payload = [
            {
                "document_id": item.document_id,
                "filename": item.filename,
                "title": item.title,
                "hits": item.hits,
                "score": item.best_score,
                "excerpt": item.excerpt,
            }
            for item in shortlist
        ]
        messages = [
            ChatMessage(
                role="system",
                content=render_prompt(
                    "verbatim_select.md",
                    candidates=json.dumps(payload, ensure_ascii=False, indent=2),
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"用户任务：{query}\n"
                    f"原文输出步骤：{step_description or '（未指定）'}\n"
                    "请选择最合适的一篇；没有合适文档时 document_id 返回空字符串。"
                ),
            ),
        ]
        try:
            choice = await self._llm.chat_structured(
                messages,
                VerbatimChoice,
                temperature=0.0,
                max_retries=1,
            )
        except Exception as exc:  # 结构化失败时回退到检索排序
            logger.warning(
                "原文选择模型调用失败，回退到检索排序",
                extra={
                    "event": "verbatim_select_failed",
                    "status": "warning",
                    "error": str(exc),
                },
            )
            return None

        valid_ids = {item.document_id for item in shortlist}
        if choice.document_id not in valid_ids:
            logger.warning(
                "原文选择返回了非法文档 id",
                extra={
                    "event": "verbatim_select_invalid",
                    "status": "warning",
                    "document_id": choice.document_id,
                },
            )
            return None
        return choice

    @staticmethod
    def _document_by_id(documents: Sequence[DocumentInfo], document_id: str) -> DocumentInfo:
        for document in documents:
            if document.document_id == document_id:
                return document
        raise VerbatimDocumentNotFoundError("选中的文档不在当前检索范围内")

    async def _read_and_build(
        self,
        document: DocumentInfo,
        *,
        selection: str,
        reason: str,
    ) -> VerbatimOutput:
        try:
            resolved = await self._document_service_provider().read_document_text(
                document.document_id
            )
        except DocumentLoadError as exc:
            raise VerbatimDocumentNotFoundError(f"读取原文失败：{exc}") from exc
        if resolved is None:
            raise VerbatimDocumentNotFoundError("文档原文件缺失或无法解析，无法输出原文")
        filename, title, text = resolved
        chars = len(text)
        if chars > self._max_chars:
            raise VerbatimDocumentTooLargeError(chars, self._max_chars)
        logger.info(
            "知识库原文准备完成",
            extra={
                "event": "verbatim_ready",
                "status": "ok",
                "document_id": document.document_id,
                "chars": chars,
                "selection": selection,
            },
        )
        return VerbatimOutput(
            document_id=document.document_id,
            filename=filename,
            title=title or Path(filename).stem,
            content=text,
            chars=chars,
            selection=selection,
            reason=reason,
        )


def verbatim_summary(output: VerbatimOutput | None) -> dict[str, Any] | None:
    """任务结果里的原文元数据（绝不包含正文，正文已在 final_answer）。"""
    if output is None:
        return None
    return {
        "document_id": output.get("document_id", ""),
        "filename": output.get("filename", ""),
        "title": output.get("title", ""),
        "chars": int(output.get("chars", 0)),
        "selection": output.get("selection", ""),
        "reason": output.get("reason", ""),
    }
