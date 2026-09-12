"""Live-path integration test for the routed pairwise contradiction scan (Fix A).

Exercises the real wired path — `scan_document_pair_routed` → `_run_embedding_scan`
→ `scan_claims_nli` — with only the external boundaries stubbed (the NLI model,
the embedder, and ChromaDB retrieval). This is the path `run_contradiction_scan`
now drives in production; before Fix A it was dead code and the pipeline used a
per-claim global scan that collapsed claim contradictions and missed partners.

The two documents are polarity-flipped variants of the same report (the real
failure case): each of doc A's claims contradicts the aligned claim in doc B.
"""

import pytest

from app.contradiction import detector


# Doc A (pessimistic) vs Doc B (optimistic) — aligned, polarity-flipped claims.
DOC_A = "docA"
DOC_B = "docB"
A_CLAIMS = {
    "docA_claim_0": "Congestion showed minimal improvement after deployment.",
    "docA_claim_1": "Implementation costs exceeded productivity gains.",
}
B_CLAIMS = {
    "docB_claim_0": "Congestion dropped significantly after deployment.",
    "docB_claim_1": "Productivity gains offset implementation costs.",
}
# Which (A, B) claim texts are genuine contradictions.
OPPOSITES = {
    (A_CLAIMS["docA_claim_0"], B_CLAIMS["docB_claim_0"]),
    (A_CLAIMS["docA_claim_1"], B_CLAIMS["docB_claim_1"]),
}


class _FakeClaimsCollection:
    """Stands in for the ChromaDB claims collection in _run_embedding_scan."""

    def get(self, where=None, include=None, **kwargs):
        doc_id = (where or {}).get("document_id")
        claims = A_CLAIMS if doc_id == DOC_A else (B_CLAIMS if doc_id == DOC_B else {})
        return {"ids": list(claims), "documents": list(claims.values())}


def _fake_query_similar(org_id, query_embedding, top_k=10, where_filter=None):
    """Return doc B's claims as candidates (retrieval restricted to the partner)."""
    target = (where_filter or {}).get("document_id")
    pool = B_CLAIMS if target == DOC_B else A_CLAIMS if target == DOC_A else {}
    ids = list(pool)
    return {
        "ids": [ids],
        "documents": [[pool[i] for i in ids]],
        "metadatas": [[{"document_id": target, "is_claim": True} for _ in ids]],
        "distances": [[0.1 for _ in ids]],  # similarity 0.9 — clears the gate
    }


def _fake_classify_claim_pairs(pairs):
    """NLI stub: contradiction (high score) only for the aligned opposite pairs.

    Genuine contradictions are bidirectional, so the stub matches either ordering
    — this is what the entailment-asymmetry check (now run on every candidate)
    probes when it re-classifies the reversed pair.
    """
    out = []
    for a, b in pairs:
        if (a, b) in OPPOSITES or (b, a) in OPPOSITES:
            out.append({"label": "contradiction", "score": 0.95})
        else:
            out.append({"label": "neutral", "score": 0.10})
    return out


@pytest.fixture
def stub_detector(monkeypatch):
    # Force the embedding (claim-level) path deterministically.
    from app.contradiction.section_aligner import SectionAligner
    monkeypatch.setattr(SectionAligner, "get_structure_confidence", lambda self, text: 0.0)

    # Stub the external boundaries: embedder, retrieval, NLI, claims fetch.
    import app.ingestion.embedder as embedder
    import app.ingestion.indexer as indexer
    monkeypatch.setattr(embedder, "generate_single_embedding", lambda text: [0.1] * 384)
    monkeypatch.setattr(detector, "query_similar", _fake_query_similar)
    monkeypatch.setattr(detector, "classify_claim_pairs", _fake_classify_claim_pairs)
    monkeypatch.setattr(indexer, "get_or_create_collection", lambda *a, **k: _FakeClaimsCollection())


def test_routed_scan_detects_claim_level_contradictions(stub_detector):
    results, scan_path = detector.scan_document_pair_routed(
        org_id="org1",
        doc_a_text="Congestion showed minimal improvement. Implementation costs exceeded gains.",
        doc_b_text="Congestion dropped significantly. Productivity gains offset costs.",
        doc_a_id=DOC_A,
        doc_b_id=DOC_B,
        doc_a_chunk_ids=["docA_chunk_0"],
        doc_b_chunk_ids=["docB_chunk_0"],
    )

    # Routed to the claim-level embedding path.
    assert scan_path == "embedding"

    # Both aligned, polarity-flipped claim pairs are caught — not collapsed.
    assert len(results) == 2
    for r in results:
        assert r.classification == "CONTRADICTORY"
        assert r.scan_path == "embedding"
        # Keyed by claim embedding IDs so the caller can dedup at claim grain.
        assert r.chunk_a_id in A_CLAIMS
        assert r.chunk_b_id in B_CLAIMS

    # The two distinct contradictions map to two distinct claim pairs (no collapse).
    pairs = {(r.chunk_a_id, r.chunk_b_id) for r in results}
    assert len(pairs) == 2


def test_routed_scan_ignores_non_contradictory_claims(stub_detector):
    """A doc that only agrees with the partner yields no contradictions."""
    global OPPOSITES
    saved = OPPOSITES
    OPPOSITES = set()  # nothing is a contradiction now
    try:
        results, scan_path = detector.scan_document_pair_routed(
            org_id="org1",
            doc_a_text="Congestion showed minimal improvement. Costs exceeded gains.",
            doc_b_text="Congestion dropped significantly. Gains offset costs.",
            doc_a_id=DOC_A,
            doc_b_id=DOC_B,
            doc_a_chunk_ids=["docA_chunk_0"],
            doc_b_chunk_ids=["docB_chunk_0"],
        )
        assert scan_path == "embedding"
        assert results == []
    finally:
        OPPOSITES = saved
