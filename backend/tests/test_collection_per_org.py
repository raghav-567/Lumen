"""Tests for Change 4: Multi-Tenancy — Collection-Per-Org in ChromaDB.

These tests run against a real in-memory chromadb client instead of the global
MagicMock installed by conftest.py. Against the mock, naming assertions passed
for the wrong reason (mock attributes are truthy) and routing/isolation could
not be verified at all. The fixture below restores genuine coverage.
"""

import sys
from unittest.mock import MagicMock

import pytest

from app.ingestion import indexer
from app.ingestion.indexer import (
    get_or_create_collection,
    _collection_for_type,
    verify_org_collections,
)


def _chromadb_module_names():
    return [
        name for name in list(sys.modules)
        if name in ("chromadb", "numpy") or name.startswith(("chromadb.", "numpy."))
    ]


@pytest.fixture(scope="module", autouse=True)
def real_chromadb_module():
    """Swap the conftest chromadb/numpy mocks for the real packages module-wide.

    conftest.py blanket-mocks `chromadb` and `numpy` for the rest of the suite.
    Real chromadb needs real numpy (it imports `numpy.typing`) and lazily
    imports its own submodules (`chromadb.db`, ...) at client-creation time, so
    the real packages must stay in sys.modules for the whole module's tests.
    We do the swap once (avoiding duplicate numpy objects that trigger
    RecursionError in `typing`) and restore the mocks on teardown so the rest of
    the suite is untouched.
    """
    saved = {name: sys.modules.pop(name) for name in _chromadb_module_names()}

    import numpy  # noqa: F401  (force a real import before chromadb needs it)
    import chromadb as real_chromadb

    original_indexer_chromadb = indexer.chromadb
    indexer.chromadb = real_chromadb

    yield real_chromadb

    indexer.chromadb = original_indexer_chromadb
    for name in _chromadb_module_names():
        del sys.modules[name]
    for name, mod in saved.items():
        sys.modules[name] = mod


@pytest.fixture(autouse=True)
def real_chroma(real_chromadb_module, monkeypatch):
    """Point indexer._get_client at a fresh in-memory chromadb client per test.

    Each test gets its own client so cross-org isolation is exercised against a
    real store rather than asserted against mock attribute access.
    """
    real_chromadb = real_chromadb_module

    # Fresh in-memory client — no disk persistence, isolated per test.
    try:
        client = real_chromadb.EphemeralClient()
    except AttributeError:
        from chromadb.config import Settings
        client = real_chromadb.Client(Settings(is_persistent=False))

    # Fail loudly if the global mock leaked in instead of a real client.
    assert not isinstance(client, MagicMock), "chromadb mock leaked into fixture"

    # _get_client is lru_cache-decorated; clear at setup AND teardown so a stale
    # client never leaks between tests. Keep a handle to the original wrapper
    # because monkeypatch replaces the attribute below.
    original_get_client = indexer._get_client
    original_get_client.cache_clear()
    # Collection handles are cached by name; a handle from a prior test points at
    # that test's (now-gone) client, so clear it alongside the client cache.
    indexer.invalidate_collection_cache()

    monkeypatch.setattr(indexer, "_get_client", lambda: client)

    yield client

    original_get_client.cache_clear()
    indexer.invalidate_collection_cache()


class TestCollectionNaming:
    """Verify collection naming convention."""

    def test_chunks_collection_name(self):
        """Chunks collection follows org_{id}_chunks pattern."""
        col = get_or_create_collection("test-org-123", name_suffix="chunks")
        assert col.name.startswith("org_test_org_123")
        assert col.name.endswith("_chunks")

    def test_claims_collection_name(self):
        """Claims collection follows org_{id}_claims pattern."""
        col = get_or_create_collection("test-org-123", name_suffix="claims")
        assert col.name.startswith("org_test_org_123")
        assert col.name.endswith("_claims")

    def test_different_orgs_different_collections(self):
        """Different org_ids produce different collection names."""
        col_a = get_or_create_collection("org-aaa", name_suffix="chunks")
        col_b = get_or_create_collection("org-bbb", name_suffix="chunks")
        assert col_a.name != col_b.name

    def test_collection_name_truncated_to_63(self):
        """Long org_ids are truncated to fit ChromaDB's 63-char limit."""
        long_id = "a" * 100
        col = get_or_create_collection(long_id, name_suffix="chunks")
        assert len(col.name) <= 63


class TestCollectionRouting:
    """Verify routing logic for chunks vs claims."""

    def test_route_claim_to_claims_collection(self):
        """is_claim=True routes to claims collection."""
        col = _collection_for_type("test-routing", is_claim=True)
        assert "_claims" in col.name

    def test_route_chunk_to_chunks_collection(self):
        """is_claim=False routes to chunks collection."""
        col = _collection_for_type("test-routing", is_claim=False)
        assert "_chunks" in col.name


class TestCollectionVerification:
    """Verify startup collection check."""

    def test_verify_creates_both_collections(self):
        """verify_org_collections creates and returns stats for both types."""
        stats = verify_org_collections("test-verify-org")
        assert "chunks" in stats
        assert "claims" in stats
        assert "count" in stats["chunks"]
        assert "count" in stats["claims"]
        assert "name" in stats["chunks"]
        assert "name" in stats["claims"]


class TestUpsertRouting:
    """Test that upsert correctly routes based on metadata."""

    def test_upsert_claims_go_to_claims_collection(self):
        """Claims should be stored in the claims collection."""
        from app.ingestion.indexer import upsert_embeddings, query_similar

        org = "test-upsert-claims"
        upsert_embeddings(
            org_id=org,
            ids=["claim_1"],
            embeddings=[[0.1] * 384],
            documents=["Test claim"],
            metadatas=[{"is_claim": True, "document_id": "doc1"}],
        )

        # Query the claims collection
        result = query_similar(
            org_id=org,
            query_embedding=[0.1] * 384,
            top_k=5,
            where_filter={"is_claim": True},
        )
        assert result["ids"][0], "Should find the claim in claims collection"
        assert "claim_1" in result["ids"][0]

    def test_upsert_chunks_go_to_chunks_collection(self):
        """Chunks should be stored in the chunks collection."""
        from app.ingestion.indexer import upsert_embeddings, query_similar

        org = "test-upsert-chunks"
        upsert_embeddings(
            org_id=org,
            ids=["chunk_1"],
            embeddings=[[0.2] * 384],
            documents=["Test chunk"],
            metadatas=[{"is_claim": False, "document_id": "doc1"}],
        )

        # Query the chunks collection (no is_claim filter = chunks)
        result = query_similar(
            org_id=org,
            query_embedding=[0.2] * 384,
            top_k=5,
        )
        assert result["ids"][0], "Should find the chunk in chunks collection"
        assert "chunk_1" in result["ids"][0]


class TestCrossOrgIsolation:
    """Verify that different orgs cannot see each other's data."""

    def test_org_isolation(self):
        """Data upserted under one org must not surface in another org's query."""
        from app.ingestion.indexer import upsert_embeddings, query_similar

        # Upsert distinct claims into two different orgs.
        upsert_embeddings(
            org_id="isolation-org-a",
            ids=["claim_from_a"],
            embeddings=[[0.5] * 384],
            documents=["Org A secret claim"],
            metadatas=[{"is_claim": True, "document_id": "docA"}],
        )
        upsert_embeddings(
            org_id="isolation-org-b",
            ids=["claim_from_b"],
            embeddings=[[0.5] * 384],
            documents=["Org B secret claim"],
            metadatas=[{"is_claim": True, "document_id": "docB"}],
        )

        # Query org A — should see only A's claim, never B's.
        result_a = query_similar(
            org_id="isolation-org-a",
            query_embedding=[0.5] * 384,
            top_k=5,
            where_filter={"is_claim": True},
        )
        found_a = result_a["ids"][0]
        assert "claim_from_a" in found_a
        assert "claim_from_b" not in found_a

        # Reverse direction: querying org B never returns A's claim.
        result_b = query_similar(
            org_id="isolation-org-b",
            query_embedding=[0.5] * 384,
            top_k=5,
            where_filter={"is_claim": True},
        )
        found_b = result_b["ids"][0]
        assert "claim_from_b" in found_b
        assert "claim_from_a" not in found_b
