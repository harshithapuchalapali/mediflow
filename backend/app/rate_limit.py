"""PostgreSQL-backed fixed-window rate limiting (no external services).

v1 scope: abuse-prone unauthenticated endpoints (password reset). A fixed
window aligned to the clock is good enough to stop trivial spam while being
simple and race-safe via a single atomic UPSERT.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import RateLimitEvent

# Config (overridable via env, matching the rest of the codebase).
RATE_LIMIT_PASSWORD_RESET = int(os.getenv("RATE_LIMIT_PASSWORD_RESET", "5"))
RATE_LIMIT_WINDOW_MINUTES = int(os.getenv("RATE_LIMIT_WINDOW_MINUTES", "15"))

# Keep the table small: prune rows older than this many windows on each hit.
_PRUNE_OLD_WINDOWS = 4


class RateLimitExceeded(HTTPException):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after_seconds)},
        )


def _client_key(request: Request) -> str:
    """Hashed client identifier (IP) so raw addresses are not stored."""
    host = request.client.host if request.client else "unknown"
    return hashlib.sha256(host.encode("utf-8")).hexdigest()


def _window_start(now: datetime, window_seconds: int) -> datetime:
    epoch = int(now.timestamp())
    start = epoch - (epoch % window_seconds)
    return datetime.fromtimestamp(start, tz=timezone.utc)


def check_rate_limit(
    db: Session,
    *,
    scope: str,
    request: Request,
    limit: int = RATE_LIMIT_PASSWORD_RESET,
    window_minutes: int = RATE_LIMIT_WINDOW_MINUTES,
) -> None:
    """Count one request for ``scope``/client and raise 429 if over the limit.

    The increment is committed immediately (its own transaction) so failed
    attempts that raise in the caller still count toward the limit.
    """
    now = datetime.now(timezone.utc)
    window_seconds = window_minutes * 60
    window_start = _window_start(now, window_seconds)
    key_hash = _client_key(request)

    # Opportunistic prune: drop rows from long-past windows.
    prune_before = _window_start(
        now - timedelta(minutes=window_minutes * _PRUNE_OLD_WINDOWS),
        window_seconds,
    )
    db.query(RateLimitEvent).filter(RateLimitEvent.window_start < prune_before).delete(
        synchronize_session=False
    )

    stmt = pg_insert(RateLimitEvent).values(
        scope=scope,
        key_hash=key_hash,
        window_start=window_start,
        request_count=1,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_rate_limit_events_scope_key_window",
        set_={"request_count": RateLimitEvent.request_count + 1},
    ).returning(RateLimitEvent.request_count)
    count = db.execute(stmt).scalar_one()
    db.commit()

    if count > limit:
        seconds_left = window_start + timedelta(seconds=window_seconds) - now
        raise RateLimitExceeded(max(1, int(seconds_left.total_seconds())))
