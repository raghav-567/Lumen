# API Examples

Copy-pasteable requests for the core KnowledgeDrift flows, runnable in sequence against a seeded
instance (`docker compose up -d && docker compose exec backend python scripts/seed.py`).

- Base URL: `http://localhost:8000`
- All paths are under `/api/v1`.
- Every data route requires `Authorization: Bearer <token>` and is scoped to the caller's
  organization. Cross-org access returns **404** (no existence leak); role violations return
  **403**.
- Response shapes below are taken from the actual Pydantic response models and route handlers.
  Field *values* are illustrative (matching a freshly-seeded instance); IDs are example UUIDs.

---

## 1. Auth

### Register — `POST /api/v1/auth/register`

Creates an organization and its first user. **The registering user becomes the org ADMIN.**

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@knowledgedrift.dev",
    "password": "demo-Admin-123",
    "full_name": "Demo Admin",
    "org_name": "KnowledgeDrift Demo"
  }'
```

**201 Created**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI3a...",
  "token_type": "bearer"
}
```

`400 Bad Request` if the email is already registered (`{"detail": "Email already registered"}`).

### Login — `POST /api/v1/auth/login`

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@knowledgedrift.dev", "password": "demo-Admin-123"}'
```

**200 OK**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI3a...",
  "token_type": "bearer"
}
```

`401 Unauthorized` on bad credentials (`{"detail": "Invalid credentials"}`).

Capture the token for the calls below:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@knowledgedrift.dev","password":"demo-Admin-123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

### Who am I — `GET /api/v1/auth/me`

```bash
curl -s http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"
```

**200 OK**

```json
{
  "id": "7a1c9d2e-0b34-4a1f-9c77-3e0a1b2c3d4e",
  "email": "admin@knowledgedrift.dev",
  "full_name": "Demo Admin",
  "org_id": "2f8b6a10-5d44-4c2a-8e91-1a2b3c4d5e6f",
  "role": "ADMIN",
  "is_active": true
}
```

---

## 2. Documents

### Upload — `POST /api/v1/documents/upload`

Multipart upload. Accepts PDF / DOCX / TXT / MD. Validates type and size (`MAX_FILE_SIZE_MB`,
default 50), dedupes by content hash, persists the document, and enqueues background processing.
Rate-limited per client IP (`UPLOAD_RATE_LIMIT`, default 10/minute). Requires a non-VIEWER role.

```bash
curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@policy.txt;type=text/plain"
```

**201 Created** (`DocumentResponse`; drift fields are 0 until the scan completes)

```json
{
  "id": "c3d4e5f6-1234-4abc-9def-0123456789ab",
  "title": "policy",
  "filename": "policy.txt",
  "file_type": "txt",
  "file_size": 1284,
  "page_count": null,
  "drift_score": 0.0,
  "semantic_drift_score": 0.0,
  "factual_drift_score": 0.0,
  "drift_type": null,
  "is_processed": false,
  "created_at": "2026-06-20T14:03:22.118Z"
}
```

**409 Conflict** — identical content already exists in the org (content-hash dedup):

```json
{
  "detail": {
    "message": "Document with identical content already exists",
    "existing_document_id": "a1b2c3d4-5678-4abc-9def-0123456789ab",
    "existing_title": "Urban Mobility Policy 2027 — Accelerated Electrification"
  }
}
```

Other errors: `400` for an unsupported file type or a file over the size limit.

### List — `GET /api/v1/documents`

Org-scoped, excludes soft-deleted documents. Supports `?skip=` and `?limit=` (1–200).

```bash
curl -s "http://localhost:8000/api/v1/documents?limit=50" \
  -H "Authorization: Bearer $TOKEN"
```

**200 OK** (`DocumentListResponse`)

```json
{
  "documents": [
    {
      "id": "a1b2c3d4-5678-4abc-9def-0123456789ab",
      "title": "Urban Mobility Policy 2027 — Accelerated Electrification",
      "filename": "Urban Mobility Policy 2027 — Accelerated Electrification.txt",
      "file_type": "txt",
      "file_size": 1402,
      "page_count": null,
      "drift_score": 66.7,
      "semantic_drift_score": 20.2,
      "factual_drift_score": 97.7,
      "drift_type": "factual",
      "is_processed": true,
      "created_at": "2026-06-20T13:51:09.402Z"
    }
  ],
  "total": 3
}
```

---

## 3. Document-contradiction graph — `GET /api/v1/graph/visualize`

Nodes are live documents (colored/sized by drift); edges are inter-document contradiction
relationships, weighted by the number of claim-grain contradiction pairs between the two docs.
Built entirely from the `contradiction_pairs` table — no LLM, no entity extraction.

```bash
curl -s http://localhost:8000/api/v1/graph/visualize \
  -H "Authorization: Bearer $TOKEN"
```

**200 OK** (`{nodes, links}`)

```json
{
  "nodes": [
    {
      "id": "a1b2c3d4-5678-4abc-9def-0123456789ab",
      "name": "Urban Mobility Policy 2027 — Accelerated Electrification",
      "type": "DOCUMENT",
      "label": "Urban Mobility Policy 2027 — Accelerated Electrification",
      "drift_score": 66.7,
      "factual_drift": 97.7,
      "semantic_drift": 20.2
    },
    {
      "id": "b2c3d4e5-6789-4abc-9def-0123456789ab",
      "name": "Urban Mobility Policy — Interim Compromise",
      "type": "DOCUMENT",
      "label": "Urban Mobility Policy — Interim Compromise",
      "drift_score": 66.7,
      "factual_drift": 97.6,
      "semantic_drift": 20.2
    }
  ],
  "links": [
    {
      "source": "a1b2c3d4-5678-4abc-9def-0123456789ab",
      "target": "b2c3d4e5-6789-4abc-9def-0123456789ab",
      "relation": "CONTRADICTS",
      "confidence": 0.9712,
      "weight": 11,
      "avg_confidence": 0.9143,
      "types": {}
    }
  ]
}
```

`weight` = count of contradicting claim pairs between the two documents; `confidence` = max pair
confidence; `types` = breakdown by `contradiction_type` (best-effort). It is `{}` on the seeded
demo because the rule-based taxonomy classifier (LLM disabled) leaves `contradiction_type` NULL
unless it confidently subtypes a pair — `scan_path` is always set, finer typing is not.

---

## 4. Reviews

### List contradictions — `GET /api/v1/reviews`

Org-scoped. Optional `?review_status=`, `?limit=`, `?offset=`.

```bash
curl -s "http://localhost:8000/api/v1/reviews?limit=2" \
  -H "Authorization: Bearer $TOKEN"
```

**200 OK**

```json
{
  "items": [
    {
      "id": "d4e5f6a7-1111-4abc-9def-0123456789ab",
      "chunk_a_text": "The transit authority will set the base passenger fare at 1 dollars per ride.",
      "chunk_b_text": "The transit authority will set the base passenger fare at 5 dollars per ride.",
      "doc_a_title": "Urban Mobility Policy 2027 — Accelerated Electrification",
      "doc_b_title": "Urban Mobility Policy (Revised) — Fiscal Restraint",
      "classification": "contradictory",
      "confidence": 0.9712,
      "explanation": "Contradiction detected with high confidence",
      "review_status": "PENDING",
      "reviewed_by": null,
      "reviewed_at": null,
      "review_reason": null,
      "is_temporal_evolution": false,
      "inferred_lineage": false,
      "explanation_valid": true,
      "sampled": false,
      "gate_similarity": 0.83,
      "created_at": "2026-06-20T13:52:41.770Z"
    }
  ],
  "total": 32,
  "limit": 2,
  "offset": 0
}
```

### Submit a verdict — `PATCH /api/v1/reviews/{contradiction_id}`

Requires a non-VIEWER role. `review_status` ∈ `approved | rejected | false_positive |
intentional_divergence` (case-insensitive). A pair in another org returns **404**.

```bash
curl -s -X PATCH http://localhost:8000/api/v1/reviews/d4e5f6a7-1111-4abc-9def-0123456789ab \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"review_status": "approved", "review_reason": "Genuine fare contradiction."}'
```

**200 OK**

```json
{
  "id": "d4e5f6a7-1111-4abc-9def-0123456789ab",
  "review_status": "APPROVED",
  "reviewed_by": "7a1c9d2e-0b34-4a1f-9c77-3e0a1b2c3d4e",
  "reviewed_at": "2026-06-20T14:10:55.012Z",
  "review_reason": "Genuine fare contradiction."
}
```

`400` for an invalid `review_status`; `403` if the caller is a VIEWER.

---

## 5. Admin — `GET /api/v1/admin/gate-calibration`

**Admin-only** (enforced at the router level). Analyzes sampled below-threshold pairs to validate
the similarity gate and recommend a threshold adjustment.

```bash
curl -s http://localhost:8000/api/v1/admin/gate-calibration \
  -H "Authorization: Bearer $TOKEN"
```

**200 OK**

```json
{
  "current_threshold": 0.75,
  "sample_rate": 0.05,
  "total_sampled_pairs": 6,
  "total_above_threshold_pairs": 32,
  "sampled_contradictions": 0,
  "sampled_contradiction_rate": 0.0,
  "sampled_similarity": { "avg": null, "min": null, "max": null },
  "above_threshold_similarity": { "avg": 0.8421, "min": 0.7603 },
  "recommendation": {
    "action": "NO_CHANGE",
    "suggested_threshold": 0.75,
    "reason": "Insufficient data (6 samples, need ≥10) or rate (0.0%) in acceptable range"
  }
}
```

**403 Forbidden** for a non-admin (MEMBER or VIEWER):

```json
{ "detail": "Admin role required" }
```

---

## Role & isolation quick reference

| Action | ADMIN | MEMBER | VIEWER | Cross-org |
|---|---|---|---|---|
| List / read documents, graph, reviews | ✓ | ✓ | ✓ | 404 |
| Upload / delete document, submit review, trigger scan | ✓ | ✓ | 403 | 404 |
| Admin endpoints (`/admin/*`), `/metrics`, drift-weight config | ✓ | 403 | 403 | 404 |

Verified by [`backend/tests/test_cross_org_isolation.py`](../backend/tests/test_cross_org_isolation.py).
