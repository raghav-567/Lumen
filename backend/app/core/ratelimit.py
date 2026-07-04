"""Per-client-IP rate limiting as a FastAPI dependency.

Built on the `limits` library (the engine slowapi wraps). We use a dependency
rather than slowapi's `@limiter.limit` decorator because the decorator's
`functools.wraps` wrapper breaks FastAPI's forward-ref resolution under
`from __future__ import annotations` for endpoints with `UploadFile` params.

Usage:
    @router.post("/upload", dependencies=[Depends(rate_limit(settings.UPLOAD_RATE_LIMIT))])
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

# In-process moving-window limiter. Single-instance only (fine for this demo);
# a multi-replica deployment would swap MemoryStorage for a Redis backend.
_storage = MemoryStorage()
_limiter = MovingWindowRateLimiter(_storage)


def rate_limit(limit_str: str):
    """Return a dependency enforcing `limit_str` (e.g. "10/minute") per client IP+path."""
    item = parse(limit_str)

    async def _dependency(request: Request) -> None:
        client = request.client.host if request.client else "anonymous"
        if not _limiter.hit(item, "ratelimit", client, request.url.path):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded — slow down and retry.",
            )

    return _dependency
