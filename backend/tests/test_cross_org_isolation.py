"""Cross-org isolation + role enforcement — the security-critical integration test.

Proves multi-tenant isolation end-to-end through the real FastAPI app:

  * A user in org A cannot read or mutate org B's documents, contradiction
    pairs, or alerts (and vice-versa) — every cross-org access reads as 404.
  * List endpoints only ever return the caller's own org's rows, and the
    removed `?org_id=` override can no longer widen that scope.
  * Role enforcement: a read-only VIEWER is 403'd on every mutation, while
    still being allowed to read; admin-only endpoints reject non-admins.
  * Unauthenticated requests are rejected.

Run inside the backend container:
    docker compose exec backend sh -c "PYTHONPATH=/app pytest tests/test_cross_org_isolation.py -v"
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.models.models import UserRole

API = "/api/v1"

# Run every test on a single session-scoped event loop. The SQLAlchemy async
# engine pools connections bound to the loop that created them, so per-test
# loops would raise "Event loop is closed" on pooled-connection reuse.
pytestmark = pytest.mark.asyncio(loop_scope="session")


# ── Fixtures: two fully-seeded, independent orgs ──────────────────────────


@pytest_asyncio.fixture(loop_scope="session")
async def org_a(org_factory):
    # Org A has an ADMIN, a read-only VIEWER, and a MEMBER (for the role tests).
    return await org_factory("A", roles=(UserRole.ADMIN, UserRole.VIEWER, UserRole.MEMBER))


@pytest_asyncio.fixture(loop_scope="session")
async def org_b(org_factory):
    return await org_factory("B", roles=(UserRole.ADMIN,))


# ── 1. Cross-org READ is blocked (both directions, multiple resources) ────


async def test_cross_org_document_read_is_404(client, org_a, org_b):
    # A's admin cannot fetch B's document …
    r = await client.get(f"{API}/documents/{org_b['doc_id']}", headers=org_a["headers"]["ADMIN"])
    assert r.status_code == 404, r.text
    # … and B's admin cannot fetch A's document.
    r = await client.get(f"{API}/documents/{org_a['doc_id']}", headers=org_b["headers"]["ADMIN"])
    assert r.status_code == 404, r.text
    # Sanity: each admin CAN fetch their own.
    r = await client.get(f"{API}/documents/{org_a['doc_id']}", headers=org_a["headers"]["ADMIN"])
    assert r.status_code == 200, r.text


async def test_cross_org_alert_read_is_scoped(client, org_a, org_b):
    # A's alert list never contains B's alert, and vice-versa.
    r = await client.get(f"{API}/alerts", headers=org_a["headers"]["ADMIN"])
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()["alerts"]}
    assert org_a["alert_id"] in ids
    assert org_b["alert_id"] not in ids


# ── 2. Cross-org WRITE is blocked (both directions, multiple resources) ───


async def test_cross_org_document_delete_is_404(client, org_a, org_b):
    r = await client.delete(f"{API}/documents/{org_b['doc_id']}", headers=org_a["headers"]["ADMIN"])
    assert r.status_code == 404, r.text
    r = await client.delete(f"{API}/documents/{org_a['doc_id']}", headers=org_b["headers"]["ADMIN"])
    assert r.status_code == 404, r.text


async def test_cross_org_review_submit_is_404(client, org_a, org_b):
    body = {"review_status": "APPROVED", "review_reason": "x"}
    # A's admin cannot review B's contradiction pair …
    r = await client.patch(f"{API}/reviews/{org_b['pair_id']}", json=body, headers=org_a["headers"]["ADMIN"])
    assert r.status_code == 404, r.text
    # … nor the reverse.
    r = await client.patch(f"{API}/reviews/{org_a['pair_id']}", json=body, headers=org_b["headers"]["ADMIN"])
    assert r.status_code == 404, r.text
    # Sanity: A's admin CAN review A's own pair.
    r = await client.patch(f"{API}/reviews/{org_a['pair_id']}", json=body, headers=org_a["headers"]["ADMIN"])
    assert r.status_code == 200, r.text


async def test_cross_org_review_explain_is_404(client, org_a, org_b):
    # Must 404 before any LLM call on another tenant's data.
    r = await client.post(f"{API}/reviews/{org_b['pair_id']}/explain", headers=org_a["headers"]["ADMIN"])
    assert r.status_code == 404, r.text


async def test_cross_org_alert_update_is_404(client, org_a, org_b):
    body = {"status": "acknowledged"}
    r = await client.patch(f"{API}/alerts/{org_b['alert_id']}", json=body, headers=org_a["headers"]["ADMIN"])
    assert r.status_code == 404, r.text
    r = await client.patch(f"{API}/alerts/{org_a['alert_id']}", json=body, headers=org_b["headers"]["ADMIN"])
    assert r.status_code == 404, r.text


# ── 3. The removed `?org_id=` override cannot widen scope ──────────────────


async def test_reviews_list_ignores_org_id_override(client, org_a, org_b):
    # Even if A passes B's org_id, the response stays scoped to A.
    r = await client.get(
        f"{API}/reviews", params={"org_id": org_b["org_id"]}, headers=org_a["headers"]["ADMIN"]
    )
    assert r.status_code == 200, r.text
    pair_ids = {item["id"] for item in r.json()["items"]}
    assert org_a["pair_id"] in pair_ids
    assert org_b["pair_id"] not in pair_ids


# ── 4. Role enforcement: VIEWER is read-only (403 on every mutation) ──────


async def test_viewer_can_read(client, org_a):
    r = await client.get(f"{API}/documents", headers=org_a["headers"]["VIEWER"])
    assert r.status_code == 200, r.text


async def test_viewer_cannot_delete_document(client, org_a):
    r = await client.delete(f"{API}/documents/{org_a['doc_id']}", headers=org_a["headers"]["VIEWER"])
    assert r.status_code == 403, r.text


async def test_viewer_cannot_submit_review(client, org_a):
    body = {"review_status": "APPROVED", "review_reason": "x"}
    r = await client.patch(f"{API}/reviews/{org_a['pair_id']}", json=body, headers=org_a["headers"]["VIEWER"])
    assert r.status_code == 403, r.text


async def test_viewer_cannot_update_alert(client, org_a):
    body = {"status": "acknowledged"}
    r = await client.patch(f"{API}/alerts/{org_a['alert_id']}", json=body, headers=org_a["headers"]["VIEWER"])
    assert r.status_code == 403, r.text


async def test_viewer_cannot_trigger_scan(client, org_a):
    r = await client.post(f"{API}/drift/scan", headers=org_a["headers"]["VIEWER"])
    assert r.status_code == 403, r.text


# ── 5. Admin-only endpoints reject non-admins ─────────────────────────────


async def test_admin_endpoint_rejects_viewer_and_member(client, org_a):
    for role in ("VIEWER", "MEMBER"):
        r = await client.get(f"{API}/admin/gate-calibration", headers=org_a["headers"][role])
        assert r.status_code == 403, f"{role}: {r.text}"
    # Admin passes.
    r = await client.get(f"{API}/admin/gate-calibration", headers=org_a["headers"]["ADMIN"])
    assert r.status_code == 200, r.text


async def test_admin_drift_weights_write_rejects_member(client, org_a):
    body = {"factual_weight": 0.6, "semantic_weight": 0.4}
    r = await client.put(f"{API}/admin/drift-weights", json=body, headers=org_a["headers"]["MEMBER"])
    assert r.status_code == 403, r.text


# ── 6. Unauthenticated access is rejected ─────────────────────────────────


async def test_unauthenticated_is_rejected(client):
    r = await client.get(f"{API}/documents")
    assert r.status_code in (401, 403), r.text
