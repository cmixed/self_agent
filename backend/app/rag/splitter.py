"""文本切分。

按段落优先切分，保证每个 chunk 不超过 ``chunk_size``，并保留 ``chunk_overlap``
的重叠以减轻跨块语义割裂。切分参数调整后需要重新评估检索效果（§11）。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.rag.loader import LoadedPage

_PARAGRAPH_SEPARATOR = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Chunk:
    """一个待向量化的文本块。"""

    index: int
    text: str
    page: int | None


def split_pages(
    pages: Sequence[LoadedPage],
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> list[Chunk]:
    """把页面切分为文本块。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须为正整数")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须满足 0 <= overlap < chunk_size")

    chunks: list[Chunk] = []
    for page in pages:
        for text in _split_text(page.text, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
            chunks.append(Chunk(index=len(chunks), text=text, page=page.page))
    return chunks


def _split_text(text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    paragraphs = [part.strip() for part in _PARAGRAPH_SEPARATOR.split(text) if part.strip()]
    pieces: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            pieces.append(current)
            tail = current[-chunk_overlap:] if chunk_overlap else ""
            current = f"{tail}\n\n{paragraph}" if tail else paragraph
        else:
            current = paragraph

        if len(current) > chunk_size:
            hard = _hard_split(current, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            pieces.extend(hard[:-1])
            current = hard[-1]

    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece.strip()]


def _hard_split(text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    """对超长且无段落边界的文本做定长切分。"""
    step = chunk_size - chunk_overlap
    return [text[start : start + chunk_size] for start in range(0, len(text), step)]
