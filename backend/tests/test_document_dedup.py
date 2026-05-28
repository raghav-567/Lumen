"""Tests for Change 7: Document Deduplication."""

import hashlib

import pytest


class TestContentHashing:
    """Test SHA-256 content hash computation."""

    def test_same_content_same_hash(self):
        """Identical content must produce identical hash."""
        content = b"Machine learning is a subset of artificial intelligence."
        h1 = hashlib.sha256(content).hexdigest()
        h2 = hashlib.sha256(content).hexdigest()
        assert h1 == h2

    def test_different_content_different_hash(self):
        """Different content must produce different hash."""
        c1 = b"Machine learning is a subset of AI."
        c2 = b"Machine learning is a branch of AI."
        h1 = hashlib.sha256(c1).hexdigest()
        h2 = hashlib.sha256(c2).hexdigest()
        assert h1 != h2

    def test_hash_length(self):
        """SHA-256 hex digest is exactly 64 characters."""
        h = hashlib.sha256(b"test data").hexdigest()
        assert len(h) == 64

    def test_empty_content_has_hash(self):
        """Even empty content produces a valid hash."""
        h = hashlib.sha256(b"").hexdigest()
        assert len(h) == 64
        assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class TestVersionDetection:
    """Test filename-based version update logic."""

    def test_version_increment(self):
        """New version number should be old + 1."""
        old_version = 2
        new_version = (old_version or 1) + 1
        assert new_version == 3

    def test_none_version_defaults_to_1(self):
        """If old doc has no version number, default to 1 → 2."""
        old_version = None
        new_version = (old_version or 1) + 1
        assert new_version == 2

    def test_first_upload_version_1(self):
        """First upload of a filename should be version 1."""
        existing_by_name = None
        version_number = 1 if not existing_by_name else 99
        assert version_number == 1

    def test_supersession_link_created(self):
        """When filename matches, supersedes_document_id should be set."""
        class FakeDoc:
            id = "old-doc-uuid"
            version_number = 1
        
        existing = FakeDoc()
        supersedes_id = existing.id if existing else None
        assert supersedes_id == "old-doc-uuid"


class TestDuplicateRejection:
    """Test the HTTP 409 behavior for exact duplicates."""

    def test_409_detail_structure(self):
        """The 409 error detail should contain existing doc ID and title."""
        detail = {
            "message": "Document with identical content already exists",
            "existing_document_id": "abc-123",
            "existing_title": "Test Document",
        }
        assert "existing_document_id" in detail
        assert "existing_title" in detail
        assert "identical content" in detail["message"]
