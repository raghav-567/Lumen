"""Text chunking utilities with sliding window."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ChunkResult:
    content: str
    chunk_index: int
    start_page: int | None = None
    end_page: int | None = None
    token_count: int = 0
    is_table: bool = False


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    page_map: dict[int, int] | None = None,
) -> list[ChunkResult]:
    """Split text into overlapping chunks using word boundaries."""
    chunk_size = chunk_size or settings.CHUNK_SIZE
    chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP

    words = text.split()
    if not words:
        return []

    chunks: list[ChunkResult] = []
    idx = 0
    chunk_index = 0

    while idx < len(words):
        end = min(idx + chunk_size, len(words))
        chunk_words = words[idx:end]
        content = " ".join(chunk_words)

        start_page = None
        end_page = None
        if page_map:
            char_start = len(" ".join(words[:idx]))
            char_end = char_start + len(content)
            for page_num, page_start_char in sorted(page_map.items()):
                if page_start_char <= char_start:
                    start_page = page_num
                if page_start_char <= char_end:
                    end_page = page_num

        chunks.append(ChunkResult(
            content=content,
            chunk_index=chunk_index,
            start_page=start_page,
            end_page=end_page,
            token_count=len(chunk_words),
        ))

        chunk_index += 1
        idx += chunk_size - chunk_overlap
        if idx >= len(words):
            break

    logger.info(f"Created {len(chunks)} chunks from {len(words)} words")
    return chunks
