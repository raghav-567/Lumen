"""Tests for the document-contradiction graph (GET /graph/visualize).

Exercises the pure assembly helper `build_document_contradiction_graph` with a small
fixture of documents + claim-grain contradiction pairs, asserting node count and edge
weights grouped by document pair. The route is a thin DB wrapper around this helper.
"""

from types import SimpleNamespace

from app.api.routes.drift_graph import build_document_contradiction_graph


def _doc(doc_id, title, drift):
    return SimpleNamespace(
        id=doc_id, title=title, filename=f"{title}.pdf",
        drift_score=drift, factual_drift_score=drift, semantic_drift_score=drift / 2,
    )


def _pair(claim_a, claim_b, conf, ctype=None, chunk_a=None, chunk_b=None):
    return SimpleNamespace(
        claim_a_id=claim_a, claim_b_id=claim_b,
        chunk_a_id=chunk_a, chunk_b_id=chunk_b,
        confidence=conf, contradiction_type=ctype,
    )


# 3 docs; claims a1/a2→A, b1/b2→B, c1→C.
DOCS = [_doc("A", "Doc2", 71.6), _doc("B", "Docc1", 70.7), _doc("C", "Doc3", 49.3)]
CLAIM_TO_DOC = {"a1": "A", "a2": "A", "b1": "B", "b2": "B", "c1": "C"}
CHUNK_TO_DOC = {"chA": "A", "chB": "B", "chC": "C"}


def _links_by_pair(links):
    return {tuple(sorted((l["source"], l["target"]))): l for l in links}


def test_nodes_are_one_per_document():
    nodes, _ = build_document_contradiction_graph(DOCS, [], CLAIM_TO_DOC, CHUNK_TO_DOC)
    assert len(nodes) == 3
    assert {n["id"] for n in nodes} == {"A", "B", "C"}
    assert all(n["type"] == "DOCUMENT" for n in nodes)
    a = next(n for n in nodes if n["id"] == "A")
    assert a["drift_score"] == 71.6 and a["label"] == "Doc2"


def test_edges_grouped_and_weighted_by_document_pair():
    pairs = [
        _pair("a1", "b1", 1.00, "direct_opposition"),
        _pair("a2", "b2", 0.90),
        _pair("a1", "b2", 0.95, "outcome_inversion"),  # A–B weight 3
        _pair("a1", "c1", 0.80),                         # A–C weight 1
        _pair("b1", "c1", 0.70),                         # B–C weight 1
        _pair("a1", "a2", 0.99),                         # self-pair (A–A) -> skipped
    ]
    nodes, links = build_document_contradiction_graph(DOCS, pairs, CLAIM_TO_DOC, CHUNK_TO_DOC)

    assert len(nodes) == 3
    by_pair = _links_by_pair(links)
    assert set(by_pair) == {("A", "B"), ("A", "C"), ("B", "C")}  # no self-pair

    ab = by_pair[("A", "B")]
    assert ab["weight"] == 3
    assert ab["relation"] == "CONTRADICTS"
    assert ab["confidence"] == 1.0                       # max
    assert ab["avg_confidence"] == round((1.0 + 0.90 + 0.95) / 3, 4)
    assert ab["types"] == {"direct_opposition": 1, "outcome_inversion": 1}

    assert by_pair[("A", "C")]["weight"] == 1
    assert by_pair[("B", "C")]["weight"] == 1
    # A–B is the heaviest edge (polar opposites), matching the live forensic read.
    assert ab["weight"] > by_pair[("A", "C")]["weight"]


def test_chunk_fallback_when_claim_ids_missing():
    # Legacy/chunk-fallback row: claim ids None, resolve via chunk_to_doc.
    pairs = [_pair(None, None, 0.88, chunk_a="chA", chunk_b="chB")]
    _, links = build_document_contradiction_graph(DOCS, pairs, CLAIM_TO_DOC, CHUNK_TO_DOC)
    assert len(links) == 1
    assert tuple(sorted((links[0]["source"], links[0]["target"]))) == ("A", "B")
    assert links[0]["weight"] == 1


def test_pairs_touching_unknown_or_deleted_docs_are_skipped():
    # 'z1' resolves to a doc not in the live node set -> edge dropped.
    pairs = [_pair("a1", "z1", 0.9)]
    claim_to_doc = {**CLAIM_TO_DOC, "z1": "Z"}  # Z is not in DOCS
    _, links = build_document_contradiction_graph(DOCS, pairs, claim_to_doc, CHUNK_TO_DOC)
    assert links == []


def test_empty_edges_still_returns_document_nodes():
    nodes, links = build_document_contradiction_graph(DOCS, [], CLAIM_TO_DOC, CHUNK_TO_DOC)
    assert len(nodes) == 3
    assert links == []
