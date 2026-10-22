"""从知识库文档生成技能草稿（编排层）。

流程（AGENTS.md §4.1 / §11）：

    文档 id → 取原文件 → 解析文本（线程）
      → 短文档：一次生成
      → 长文档：分块提炼 → 去重 → 合并为单个技能
      → 草稿 + 提示

设计约束：

- **只出草稿，不落库**：用户在前端确认/编辑后走既有 ``POST /api/skills``，
  因此生成失败或质量差不会污染技能库；
- 文档解析复用 ``rag.loader.load_document``（PDF/MD/TXT 同一入口），
  与文档入库链路保持一致；
- 长文档不再截断到只看开头：按 ``max_chars`` 切块（最多
  ``MAX_SKILL_GENERATION_CHUNKS`` 段），每段只提炼可执行做法，再合并去重；
  超出块数/合并输入超限都写进 ``warnings`` 并置 ``truncated``；
- 确定性检查（触发条件、同名、指令超长）不调模型，结果放进 ``warnings`` /
  ``duplicate_of``。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.agents.skill_generator import (
    ChunkExtractionModel,
    extract_chunk_methods,
    generate_skill_draft,
    merge_skill_notes,
)
from app.core.limits import (
    MAX_SKILL_EXTRACTION_CHARS,
    MAX_SKILL_GENERATION_CHUNKS,
    MAX_SKILL_INSTRUCTION_CHARS,
)
from app.core.logging import get_logger
from app.llm.base import LLMProvider
from app.memory.repository import SkillRecord
from app.rag.loader import DocumentError, load_document
from app.services.document_service import DocumentService
from app.services.skill_service import SkillService

logger = get_logger(__name__)

# 单次生成最多使用的文档数（与 API Schema 的上限保持一致）
MAX_GENERATION_DOCUMENTS = 3
# name/description 的落库上限（与 SkillCreate 一致），超长自动截断并提示
MAX_NAME_LENGTH = 60
MAX_DESCRIPTION_LENGTH = 200
MAX_SOURCE_LENGTH = 260
# 少于这个长度的指令通常不可执行，只提示不拒绝
MIN_CONTENT_LENGTH = 80


class SkillGenerationError(Exception):
    """生成技能草稿失败（API 层据此映射为可读错误）。"""

    error_type = "skill_generation_failed"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SkillDocumentNotFoundError(SkillGenerationError):
    """指定的文档不存在（或原文件已丢失）。"""

    error_type = "skill_document_not_found"


class SkillDocumentEmptyError(SkillGenerationError):
    """文档解析后没有任何文本。"""

    error_type = "skill_document_empty"


@dataclass(frozen=True)
class SkillDraftResult:
    """生成结果（尚未落库）。"""

    name: str
    description: str
    content: str
    source_filename: str | None
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)
    duplicate_of: tuple[str, str] | None = None  # (skill_id, name)


def _normalize_name(name: str) -> str:
    return "".join(name.split()).lower()


def _has_trigger(description: str) -> bool:
    """适用场景是否写明了触发条件（供 Planner 判断，不追求严格语义）。"""
    return any(marker in description for marker in ("当", "时使用", "时，", "用于", "适用"))


def _normalize_note(value: str) -> str:
    return "".join(value.split()).lower()


def _split_text(text: str, size: int) -> list[str]:
    """按上限切分文本，优先在段落/句子边界断开。"""
    chunks: list[str] = []
    start = 0
    total = len(text)
    while start < total:
        end = min(total, start + size)
        if end < total:
            # 只在最后 20% 找断点，避免段落边界把每块切成半块、
            # 让长文档白白多消耗块数配额。
            floor = start + int(size * 0.8)
            cut = text.rfind("\n", floor, end)
            if cut < 0:
                cut = text.rfind("。", floor, end)
            if cut >= 0:
                end = cut + 1
        chunks.append(text[start:end])
        start = end
    return chunks


def _render_extraction_notes(
    extraction: ChunkExtractionModel, chunk_index: int, seen: set[tuple[str, tuple[str, ...]]]
) -> str:
    """把结构化做法渲染成紧凑文本，并按「名称 + 步骤」去重。"""
    lines: list[str] = []
    for method in extraction.methods:
        name = method.name.strip()
        if not name:
            continue
        steps = [step.strip() for step in method.steps if step.strip()]
        checks = [check.strip() for check in method.checks if check.strip()]
        key = (_normalize_note(name), tuple(_normalize_note(step) for step in steps))
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- 方法：{name}")
        if method.when.strip():
            lines.append(f"  适用：{method.when.strip()}")
        if steps:
            lines.append("  步骤：" + "；".join(steps))
        if checks:
            lines.append("  检查：" + "；".join(checks))
    if not lines:
        return ""
    return f"【片段 {chunk_index}】\n" + "\n".join(lines)


def _clip_notes(notes: str, max_chars: int) -> tuple[str, bool]:
    """合并输入也有预算：超出时在行边界节选并显式提示。"""
    if len(notes) <= max_chars:
        return notes, False
    window = notes[:max_chars]
    cut = window.rfind("\n")
    if cut >= int(max_chars * 0.7):
        window = window[:cut]
    return window.rstrip(), True


def _clip_instruction(content: str, max_chars: int) -> str:
    """技能指令落库前截断；优先保留完整的段落/句子。"""
    if len(content) <= max_chars:
        return content
    window = content[:max_chars]
    cut = max(window.rfind("\n"), window.rfind("。"), window.rfind("；"))
    if cut >= int(max_chars * 0.7):
        window = window[: cut + 1]
    return window.rstrip()


class SkillGenerationService:
    """把「文档」变成「可审核的技能草稿」。"""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        document_service: DocumentService,
        skill_service: SkillService,
        max_chars: int = 12000,
    ) -> None:
        self._llm = llm
        self._document_service = document_service
        self._skill_service = skill_service
        self._max_chars = max(1000, max_chars)

    async def generate(self, *, document_ids: Sequence[str], hint: str = "") -> SkillDraftResult:
        unique_ids = list(dict.fromkeys(document_ids))
        if not unique_ids:
            raise SkillDocumentNotFoundError("请先选择至少一份文档")
        if len(unique_ids) > MAX_GENERATION_DOCUMENTS:
            raise SkillGenerationError(
                f"一次最多使用 {MAX_GENERATION_DOCUMENTS} 份文档，请减少选择"
            )

        sections: list[str] = []
        filenames: list[str] = []
        for document_id in unique_ids:
            filename, text = await self._document_text(document_id)
            filenames.append(filename)
            sections.append(f"【文档：{filename}】\n{text}")

        combined = "\n\n".join(sections)
        input_chars = len(combined)
        warnings: list[str] = []
        truncated = False
        chunks_used = 1
        mode = "single"

        if input_chars <= self._max_chars:
            draft = await generate_skill_draft(self._llm, text=combined, hint=hint)
        else:
            # 长文档：分块提炼 → 去重 → 合并为单个技能。
            # 块数有上限，避免文档越长调用次数无限增长（§27）。
            mode = "chunked"
            all_chunks = _split_text(combined, self._max_chars)
            selected = all_chunks[:MAX_SKILL_GENERATION_CHUNKS]
            chunks_used = len(selected)
            truncated = len(all_chunks) > MAX_SKILL_GENERATION_CHUNKS
            if truncated:
                warnings.append(
                    f"文档过长，仅分析前 {MAX_SKILL_GENERATION_CHUNKS} 段"
                    f"（每段约 {self._max_chars} 字）"
                )

            seen: set[tuple[str, tuple[str, ...]]] = set()
            note_blocks: list[str] = []
            for index, chunk in enumerate(selected, start=1):
                extraction = await extract_chunk_methods(
                    self._llm,
                    text=chunk,
                    chunk_index=index,
                    chunk_total=chunks_used,
                )
                block = _render_extraction_notes(extraction, index, seen)
                if block:
                    note_blocks.append(block)

            notes = "\n\n".join(note_blocks)
            if not notes:
                # 概念型资料可能提炼不出明确方法：回退到第一段生成，
                # 并如实说明只用了第一段，而不是假装处理了全文。
                draft = await generate_skill_draft(self._llm, text=selected[0], hint=hint)
                truncated = True
                warnings.append("未能从分块中提炼出可执行方法，已回退为仅使用第 1 段生成")
            else:
                notes, notes_clipped = _clip_notes(notes, MAX_SKILL_EXTRACTION_CHARS)
                if notes_clipped:
                    truncated = True
                    warnings.append(f"分块提炼结果过长，仅合并前 {MAX_SKILL_EXTRACTION_CHARS} 字")
                draft = await merge_skill_notes(self._llm, notes=notes, hint=hint)
                if chunks_used > 1:
                    warnings.append(f"文档较长，已分 {chunks_used} 段提炼后合并")

        name = draft.name.strip()[:MAX_NAME_LENGTH]
        description = draft.description.strip()[:MAX_DESCRIPTION_LENGTH]
        content = draft.content.strip()
        if not name or not description or not content:
            raise SkillGenerationError("模型返回的技能内容为空，请重试或换一份文档")
        if len(content) > MAX_SKILL_INSTRUCTION_CHARS:
            content = _clip_instruction(content, MAX_SKILL_INSTRUCTION_CHARS)
            truncated = True
            warnings.append(f"技能指令超过 {MAX_SKILL_INSTRUCTION_CHARS} 字，已自动截断")

        if len(draft.name.strip()) > MAX_NAME_LENGTH:
            warnings.append(f"技能名称超过 {MAX_NAME_LENGTH} 字，已自动截断")
        if len(draft.description.strip()) > MAX_DESCRIPTION_LENGTH:
            warnings.append(f"适用场景超过 {MAX_DESCRIPTION_LENGTH} 字，已自动截断")
        if not _has_trigger(description):
            warnings.append(
                "适用场景没有写明触发条件（建议写成「当……时使用」），Planner 可能不会选中它"
            )
        if len(content) < MIN_CONTENT_LENGTH:
            warnings.append("技能指令较短，可能不够可执行，建议补充步骤与输出要求")

        existing = await self._skill_service.list_skills()
        duplicate = self._find_duplicate(existing, name)

        logger.info(
            "技能草稿生成",
            extra={
                "node": "skill_generator",
                "event": "skill_draft_generated",
                "status": "ok",
                "documents": len(unique_ids),
                "chars": input_chars,
                "mode": mode,
                "chunks": chunks_used,
                "truncated": truncated,
            },
        )
        return SkillDraftResult(
            name=name,
            description=description,
            content=content,
            source_filename=self._join_filenames(filenames),
            truncated=truncated,
            warnings=warnings,
            duplicate_of=duplicate,
        )

    async def _document_text(self, document_id: str) -> tuple[str, str]:
        """取文档原文件并解析为纯文本；失败时抛出可读错误。"""
        located = await self._document_service.document_file(document_id)
        if located is None:
            raise SkillDocumentNotFoundError(f"文档不存在或原文件已丢失：{document_id}")
        path, filename = located
        try:
            pages = await asyncio.to_thread(load_document, path)
        except DocumentError as exc:
            raise SkillDocumentEmptyError(f"无法解析文档「{filename}」：{exc.message}") from exc
        text = "\n".join(page.text for page in pages).strip()
        if not text:
            raise SkillDocumentEmptyError(f"文档「{filename}」没有可用文本")
        return filename, text

    @staticmethod
    def _join_filenames(filenames: list[str]) -> str | None:
        if not filenames:
            return None
        return " + ".join(filenames)[:MAX_SOURCE_LENGTH]

    @staticmethod
    def _find_duplicate(existing: Sequence[SkillRecord], name: str) -> tuple[str, str] | None:
        target = _normalize_name(name)
        for skill in existing:
            if _normalize_name(skill.name) == target:
                return skill.skill_id, skill.name
        return None
