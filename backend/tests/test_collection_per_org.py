"""Tests for Change 4: Multi-Tenancy — Collection-Per-Org in ChromaDB."""

import pytest

from app.ingestion.indexer import (
    get_or_create_collection,
    _collection_for_type,
    verify_org_collections,
)


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
        """Data from org A should not appear in org B queries."""
        from app.ingestion.indexer import upsert_embeddings, query_similar

        # Insert into org A
        upsert_embeddings(
            org_id="isolation-org-a",
            ids=["isolated_claim_1"],
            embeddings=[[0.5] * 384],
            documents=["Org A secret claim"],
            metadatas=[{"is_claim": True, "document_id": "docA"}],
        )

        # Query from org B — should find nothing
        result = query_similar(
            org_id="isolation-org-b",
            query_embedding=[0.5] * 384,
            top_k=5,
            where_filter={"is_claim": True},
        )
        found_ids = result["ids"][0] if result["ids"] else []
        assert "isolated_claim_1" not in found_ids
