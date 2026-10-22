"""从知识库文档生成技能草稿（编排层）。

流程（AGENTS.md §4.1 / §11）：

    文档 id → 取原文件 → 解析文本（线程） → 截断 → 调模型 → 草稿 + 提示

设计约束：

- **只出草稿，不落库**：用户在前端确认/编辑后走既有 ``POST /api/skills``，
  因此生成失败或质量差不会污染技能库；
- 文档解析复用 ``rag.loader.load_document``（PDF/MD/TXT 同一入口），
  与文档入库链路保持一致；
- 截断是显式的：返回 ``truncated`` 让前端如实告知用户；
- 确定性检查（触发条件、同名）不调模型，结果放进 ``warnings`` / ``duplicate_of``。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.agents.skill_generator import generate_skill_draft
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

    async def generate(
        self, *, document_ids: Sequence[str], hint: str = ""
    ) -> SkillDraftResult:
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
        truncated = len(combined) > self._max_chars
        if truncated:
            combined = combined[: self._max_chars]

        draft = await generate_skill_draft(self._llm, text=combined, hint=hint)

        name = draft.name.strip()[:MAX_NAME_LENGTH]
        description = draft.description.strip()[:MAX_DESCRIPTION_LENGTH]
        content = draft.content.strip()
        if not name or not description or not content:
            raise SkillGenerationError("模型返回的技能内容为空，请重试或换一份文档")

        warnings: list[str] = []
        if truncated:
            warnings.append(f"文档较长，仅使用前 {self._max_chars} 字生成")
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
                "chars": len(combined),
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
    def _find_duplicate(
        existing: Sequence[SkillRecord], name: str
    ) -> tuple[str, str] | None:
        target = _normalize_name(name)
        for skill in existing:
            if _normalize_name(skill.name) == target:
                return skill.skill_id, skill.name
        return None
