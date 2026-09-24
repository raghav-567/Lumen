#!/usr/bin/env python
"""Seed script — demo org + admin + the 3 Urban Mobility policy documents.

Runs everything through the *real* HTTP + Celery pipeline (upload → ingest →
index → routed contradiction scan → drift recalc), so a fresh checkout shows a
working system on first launch: 3 documents, a cluster of cross-document
contradictions, real drift scores, and a populated contradiction graph.

Idempotent:
  * Re-running logs in instead of re-registering the admin.
  * Content-hash dedup means re-uploading the same documents is a no-op (the
    API returns 409, which we treat as "already seeded").

Usage (stack must be up — `docker compose up -d`):
    docker compose exec backend python scripts/seed.py
    # …or from the host:
    API_URL=http://localhost:8000/api/v1 python backend/scripts/seed.py

Demo credentials (also documented in the README):
    email:    admin@knowledgedrift.dev
    password: demo-Admin-123
"""
from __future__ import annotations

import os
import sys
import time
import tempfile

import requests

# Make the backend package importable when run as `python scripts/seed.py`
# (puts the backend root, parent of scripts/, on sys.path) so the in-process
# coverage pass below can import app.tasks.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API = os.getenv("API_URL", "http://localhost:8000/api/v1").rstrip("/")
ADMIN_EMAIL = os.getenv("SEED_ADMIN_EMAIL", "admin@knowledgedrift.dev")
ADMIN_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "demo-Admin-123")
ADMIN_NAME = "Demo Admin"
ORG_NAME = "KnowledgeDrift Demo"

PROCESS_TIMEOUT = int(os.getenv("SEED_PROCESS_TIMEOUT", "180"))   # per-doc indexing
SCAN_TIMEOUT = int(os.getenv("SEED_SCAN_TIMEOUT", "300"))         # contradiction scans

# ── The three Urban Mobility policy documents ─────────────────────────────
# Parallel structure, three stances. They contradict each other across seven
# topics (electrification deadline, maintenance downtime, routing priority,
# infrastructure budget, autonomous shuttles, fares, night service), which the
# routed claim-level NLI scan picks up as cross-document contradictions.

# Each document states the same fourteen policy parameters in an identical
# sentence skeleton, differing only in the (deliberately far-apart) value. The
# rule-based extractor reliably lifts each as a claim, the near-identical
# phrasing clears the similarity gate, and the value swap makes every
# cross-document pair an NLI contradiction — so all three doc pairs light up.
_SKELETON = [
    "The transit authority will require all public transit vehicles to transition to electric propulsion within {} months.",
    "The transit authority will cap fleet maintenance downtime at {} hours per vehicle per quarter.",
    "The transit authority will allocate {} million dollars for eastern corridor infrastructure upgrades.",
    "The transit authority will expand the dedicated bus lane network to {} kilometers.",
    "The transit authority will operate {} electric buses across the network.",
    "The transit authority will provide {} new park-and-ride parking spaces.",
    "The transit authority will run peak-hour service every {} minutes.",
    "The transit authority will set the base passenger fare at {} dollars per ride.",
    "The transit authority will install {} new bike-share docks.",
    "The transit authority will deploy {} vehicle charging stations.",
    "The transit authority will retrofit {} stations for full accessibility.",
    "The transit authority will reduce transit carbon emissions by {} percent.",
    "The transit authority will operate weekend night service for {} hours.",
    "The transit authority will provide an annual operating subsidy of {} million dollars.",
]

# Aggressive / restraint / compromise values for each parameter above.
_VALUES = {
    "Urban Mobility Policy 2027 — Accelerated Electrification":
        [24, 24, 500, 250, 4000, 6000, 4, 1, 1200, 900, 300, 60, 24, 200],
    "Urban Mobility Policy (Revised) — Fiscal Restraint":
        [96, 96, 180, 50, 1500, 1000, 15, 5, 200, 150, 60, 10, 6, 50],
    "Urban Mobility Policy — Interim Compromise":
        [60, 60, 320, 150, 2800, 3500, 9, 3, 700, 500, 180, 35, 16, 120],
}

DOCS: list[tuple[str, str]] = [
    (title, " ".join(s.format(v) for s, v in zip(_SKELETON, vals)))
    for title, vals in _VALUES.items()
]


def _auth_token() -> str:
    """Register the demo admin (idempotent) and return an access token."""
    r = requests.post(f"{API}/auth/register", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
        "full_name": ADMIN_NAME, "org_name": ORG_NAME,
    }, timeout=30)
    if r.status_code == 201:
        print(f"  ✓ Registered demo admin + org '{ORG_NAME}'")
        return r.json()["access_token"]
    if r.status_code == 400:  # already registered → log in
        r = requests.post(f"{API}/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
        }, timeout=30)
        r.raise_for_status()
        print("  ✓ Demo admin already exists — logged in")
        return r.json()["access_token"]
    r.raise_for_status()
    raise SystemExit(f"Unexpected auth response: {r.status_code} {r.text}")


def _upload(headers: dict, title: str, content: str) -> str | None:
    """Upload one document. Returns its id, or None if it already existed."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=True) as f:
        f.write(content)
        f.flush()
        with open(f.name, "rb") as fh:
            r = requests.post(
                f"{API}/documents/upload",
                files={"file": (f"{title}.txt", fh, "text/plain")},
                headers=headers, timeout=60,
            )
    if r.status_code == 201:
        doc_id = r.json()["id"]
        print(f"  ✓ Uploaded: {title}")
        return doc_id
    if r.status_code == 409:  # content-hash dedup → already seeded
        print(f"  • Already present (dedup): {title}")
        return None
    r.raise_for_status()
    return None


def _wait_processed(headers: dict, doc_id: str, timeout: int) -> None:
    """Poll until a document finishes indexing (is_processed)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{API}/documents", headers=headers, timeout=30)
        r.raise_for_status()
        for d in r.json()["documents"]:
            if d["id"] == doc_id and d.get("is_processed"):
                return
        time.sleep(3)
    print(f"  ! Timed out waiting for {doc_id} to index (continuing)")


def _metrics(headers: dict) -> dict:
    r = requests.get(f"{API.rsplit('/api/v1', 1)[0]}/metrics", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def _wait_claims_indexed(headers: dict, prev_total: int, timeout: int) -> int:
    """Wait until the contradiction scan has indexed this doc's claims.

    Claims are indexed inside run_contradiction_scan (after chunk indexing), so
    `is_processed` alone doesn't guarantee a later doc's shortlist will see this
    one. We block until org-wide total_claims grows past `prev_total` and holds
    steady — only then are this doc's claims in the vector store.
    """
    deadline = time.time() + timeout
    last, stable = prev_total, 0
    while time.time() < deadline:
        try:
            count = _metrics(headers)["pipeline"]["total_claims"]
        except Exception:
            count = prev_total
        if count > prev_total and count == last:
            stable += 1
            if stable >= 2:
                return count
        else:
            stable = 0
        last = count
        time.sleep(3)
    return max(last, prev_total)


def _wait_for_scans(headers: dict, timeout: int) -> int:
    """Poll the org-scoped metrics until the contradiction count stabilizes."""
    deadline = time.time() + timeout
    last, stable = -1, 0
    while time.time() < deadline:
        try:
            count = _metrics(headers)["detection"]["total_contradictions"]
        except Exception:
            count = -1
        if count > 0 and count == last:
            stable += 1
            if stable >= 3:  # unchanged across 3 polls → scans settled
                return count
        else:
            stable = 0
        last = count
        print(f"    … contradictions so far: {max(count, 0)}")
        time.sleep(5)
    return max(last, 0)


def _full_mesh_coverage(headers: dict, fallback: int) -> int:
    """Scan every unordered document pair in-process (idempotent gap-fill).

    Only possible when app modules are importable (i.e. running inside the
    backend container). Returns the resulting contradiction count, or `fallback`
    if skipped (pure-HTTP host run — relies on the incremental scan instead).
    """
    try:
        from app.tasks.tasks import scan_document_pair, recalculate_drift_scores
    except Exception as e:
        print(f"  (coverage pass skipped — app not importable: {e})")
        return fallback  # host-mode HTTP run — app not importable

    import itertools

    me = requests.get(f"{API}/auth/me", headers=headers, timeout=30).json()
    org_id = me["org_id"]
    ids = [d["id"] for d in requests.get(f"{API}/documents", headers=headers, timeout=30).json()["documents"]]
    if len(ids) < 2:
        return fallback

    print(f"  Coverage pass: scanning {len(ids) * (len(ids) - 1) // 2} document pair(s) …")
    for a, b in itertools.combinations(ids, 2):
        scan_document_pair(org_id, a, b)
    recalculate_drift_scores(org_id=org_id)
    return _metrics(headers)["detection"]["total_contradictions"]


def main() -> None:
    print(f"Seeding KnowledgeDrift demo data via {API} …")
    headers = {"Authorization": f"Bearer {_auth_token()}"}

    # Upload sequentially, waiting for each doc's CLAIMS to be indexed before
    # the next upload, so every later document's scan shortlist finds the
    # earlier ones as candidates (otherwise pairs get silently skipped).
    new_ids = []
    claims_total = 0
    for title, content in DOCS:
        doc_id = _upload(headers, title, content)
        if doc_id:
            _wait_processed(headers, doc_id, PROCESS_TIMEOUT)
            claims_total = _wait_claims_indexed(headers, claims_total, PROCESS_TIMEOUT)
            new_ids.append(doc_id)

    if new_ids:
        print("  Waiting for contradiction scans to settle …")
        contradictions = _wait_for_scans(headers, SCAN_TIMEOUT)
    else:
        contradictions = _metrics(headers)["detection"]["total_contradictions"]

    # ── Deterministic coverage pass ──
    # The incremental per-upload fan-out can miss a document pair under an
    # indexing race (chroma claim-indexing lagging the DB commit), leaving the
    # contradiction graph short an edge. When run inside the backend container
    # (the documented path) we close that gap by scanning every unordered
    # document pair in-process. This is idempotent — the claim-grain unique
    # index dedupes pairs already found — so it only fills gaps.
    contradictions = _full_mesh_coverage(headers, fallback=contradictions)

    # ── Summary ──
    docs = requests.get(f"{API}/documents", headers=headers, timeout=30).json()
    scores = requests.get(f"{API}/drift/scores", headers=headers, timeout=30).json()["scores"]
    graph = requests.get(f"{API}/graph/visualize", headers=headers, timeout=30).json()

    print("\n──────── Seed complete ────────")
    print(f"  Documents:      {docs['total']}")
    print(f"  Contradictions: {contradictions}")
    print(f"  Graph:          {len(graph['nodes'])} nodes, {len(graph['links'])} edges")
    print("  Drift scores:")
    for s in sorted(scores, key=lambda x: x["drift_score"], reverse=True):
        print(f"    {s['drift_score']:5.1f}  (factual {s['factual_drift_score']:.1f} / "
              f"semantic {s['semantic_drift_score']:.1f})  {s['title']}")
    print("\n  Log in at the frontend with:")
    print(f"    email:    {ADMIN_EMAIL}")
    print(f"    password: {ADMIN_PASSWORD}")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"\nSeed failed (is the stack up? `docker compose up -d`): {e}", file=sys.stderr)
        sys.exit(1)
