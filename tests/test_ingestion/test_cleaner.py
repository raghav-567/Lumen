"""Tests for text cleaner."""

import pytest
from app.ingestion.cleaner import clean_text, normalize_whitespace


def test_clean_text_whitespace():
    """Extra whitespace is collapsed."""
    result = clean_text("hello   world\n\n\nfoo")
    assert "   " not in result


def test_clean_text_empty():
    """Empty string returns empty."""
    assert clean_text("") == ""


def test_clean_text_unicode_quotes():
    """Smart quotes are normalized."""
    result = clean_text("\u201cHello\u201d")
    assert '"' in result


def test_normalize_whitespace():
    """Multiple spaces become one."""
    result = normalize_whitespace("  hello   world  ")
    assert result == "hello world"
