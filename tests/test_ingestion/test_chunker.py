"""Tests for text chunking."""

import pytest
from app.ingestion.chunker import chunk_text


def test_chunk_text_basic():
    """Basic chunking produces non-empty results."""
    text = " ".join(["word"] * 1000)
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
    assert len(chunks) > 1
    assert all(c.content for c in chunks)


def test_chunk_text_empty():
    """Empty text produces no chunks."""
    chunks = chunk_text("")
    assert chunks == []


def test_chunk_text_overlap():
    """Chunks should overlap when overlap > 0."""
    text = " ".join(f"word{i}" for i in range(200))
    chunks = chunk_text(text, chunk_size=50, chunk_overlap=10)
    if len(chunks) > 1:
        last_words_0 = set(chunks[0].content.split()[-10:])
        first_words_1 = set(chunks[1].content.split()[:10])
        assert last_words_0 & first_words_1  # should overlap


def test_chunk_indices():
    """Chunk indices should be sequential."""
    text = " ".join(["word"] * 500)
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))
