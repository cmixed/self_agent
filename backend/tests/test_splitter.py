from __future__ import annotations

import pytest

from app.rag.loader import LoadedPage
from app.rag.splitter import split_pages


def test_short_text_yields_single_chunk() -> None:
    chunks = split_pages(
        [LoadedPage(page=None, text="很短的一段文字")], chunk_size=100, chunk_overlap=10
    )

    assert len(chunks) == 1
    assert chunks[0].text == "很短的一段文字"
    assert chunks[0].index == 0
    assert chunks[0].page is None


def test_long_text_is_split_within_size_limit() -> None:
    paragraphs = [f"第{i}段：" + "内容" * 60 for i in range(10)]
    text = "\n\n".join(paragraphs)

    chunks = split_pages([LoadedPage(page=1, text=text)], chunk_size=200, chunk_overlap=40)

    assert len(chunks) > 1
    # 不变量：每个 chunk 不超过 chunk_size，且都非空
    assert all(len(chunk.text) <= 200 for chunk in chunks)
    assert all(chunk.text.strip() for chunk in chunks)
    # 索引连续
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    # 页码被保留
    assert {chunk.page for chunk in chunks} == {1}


def test_single_huge_paragraph_is_hard_split() -> None:
    text = "字" * 500

    chunks = split_pages([LoadedPage(page=None, text=text)], chunk_size=120, chunk_overlap=20)

    assert len(chunks) >= 4
    assert all(len(chunk.text) <= 120 for chunk in chunks)


def test_invalid_overlap_rejected() -> None:
    with pytest.raises(ValueError):
        split_pages([LoadedPage(page=None, text="x")], chunk_size=100, chunk_overlap=100)
    with pytest.raises(ValueError):
        split_pages([LoadedPage(page=None, text="x")], chunk_size=0, chunk_overlap=0)


def test_blank_pages_produce_no_chunks() -> None:
    assert split_pages([LoadedPage(page=None, text="   \n\n  ")]) == []
