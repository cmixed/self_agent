"""文档解析。

把上传的原始文件解析为带页码的纯文本页面。文档处理与 Agent 解耦（§11）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class DocumentError(Exception):
    """文档处理错误基类。"""

    error_type = "document_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnsupportedDocumentError(DocumentError):
    """不支持的文件类型。"""

    error_type = "unsupported_document"


class DocumentLoadError(DocumentError):
    """文件存在但无法提取文本。"""

    error_type = "document_load_error"


SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".markdown"}


@dataclass(frozen=True)
class LoadedPage:
    """一个文档页面（TXT/MD 视为单页，page 为 None）。"""

    page: int | None
    text: str


def load_document(path: Path) -> list[LoadedPage]:
    """按扩展名解析文档，返回非空的页面列表。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = _load_pdf(path)
    elif suffix in {".txt", ".md", ".markdown"}:
        pages = _load_text(path)
    else:
        raise UnsupportedDocumentError(
            f"不支持的文件类型：{suffix or '(无扩展名)'}，仅支持 "
            f"{'、'.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    pages = [LoadedPage(page=item.page, text=item.text) for item in pages if item.text.strip()]
    if not pages:
        raise DocumentLoadError("未能从文档中提取到任何文本")
    return pages


def _load_text(path: Path) -> list[LoadedPage]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DocumentLoadError(f"读取文件失败：{exc}") from exc
    return [LoadedPage(page=None, text=text)]


def _load_pdf(path: Path) -> list[LoadedPage]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        pages = [
            LoadedPage(page=index + 1, text=page.extract_text() or "")
            for index, page in enumerate(reader.pages)
        ]
    except Exception as exc:  # noqa: BLE001 - 统一转为本层错误
        raise DocumentLoadError(f"解析 PDF 失败：{exc}") from exc
    return pages
