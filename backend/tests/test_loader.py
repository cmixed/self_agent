from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.loader import (
    DocumentLoadError,
    UnsupportedDocumentError,
    load_document,
)


def test_load_markdown_as_single_page(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("# 标题\n\n正文内容", encoding="utf-8")

    pages = load_document(path)

    assert len(pages) == 1
    assert pages[0].page is None
    assert "正文内容" in pages[0].text


def test_load_txt(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")

    assert load_document(path)[0].text == "hello"


def test_unsupported_suffix_raises(tmp_path: Path) -> None:
    path = tmp_path / "a.docx"
    path.write_bytes(b"x")

    with pytest.raises(UnsupportedDocumentError):
        load_document(path)


def test_blank_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_text("   \n  ", encoding="utf-8")

    with pytest.raises(DocumentLoadError):
        load_document(path)


def test_pdf_without_text_raises(tmp_path: Path) -> None:
    """空白 PDF 走通 PDF 解析分支，但无文本时给出可读错误。"""
    from pypdf import PdfWriter

    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(DocumentLoadError):
        load_document(path)
