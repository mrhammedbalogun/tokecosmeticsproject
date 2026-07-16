"""Two-phase idempotency for POST /checkout/. Redis (Django cache) is the fast path;
the Payment.idempotency_key UNIQUE constraint is the durable backstop in the checkout
service. Record shape: {"status": "in_progress"|"done", "request_hash", "code", "body"}."""
from __future__ import annotations

import hashlib
import json

from django.core.cache import cache

INFLIGHT_TTL = 300      # 5 min — a stuck in-progress marker self-heals
DONE_TTL = 86400        # 24 h replay window (API convention)


class IdempotencyConflict(Exception):
    """A request with this key is still in progress."""


class IdempotencyKeyReused(Exception):
    """Same key, different request payload — a client bug; never execute."""


def _key(user_id, key: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return f"idem:checkout:{user_id}:{digest}"


def hash_payload(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def begin(user_id, key: str, request_hash: str):
    """Reserve the key. Returns None to proceed, or (code, body) to replay.
    Raises IdempotencyConflict (in progress) or IdempotencyKeyReused (payload changed)."""
    cache_key = _key(user_id, key)
    placed = cache.add(
        cache_key, {"status": "in_progress", "request_hash": request_hash}, INFLIGHT_TTL
    )
    if placed:
        return None
    record = cache.get(cache_key)
    if record is None:  # expired between add() and get() — treat as fresh
        cache.set(cache_key, {"status": "in_progress", "request_hash": request_hash}, INFLIGHT_TTL)
        return None
    if record.get("request_hash") != request_hash:
        raise IdempotencyKeyReused()
    if record.get("status") == "done":
        return record["code"], record["body"]
    raise IdempotencyConflict()


def finish(user_id, key: str, request_hash: str, status_code: int, body: dict) -> None:
    cache.set(
        _key(user_id, key),
        {"status": "done", "request_hash": request_hash, "code": status_code, "body": body},
        DONE_TTL,
    )


def clear(user_id, key: str) -> None:
    """Drop the in-progress marker so the SAME key can be retried immediately — used when
    a payment gateway is temporarily down on initiate. The order stays pending; the retry
    resumes it (durable Payment backstop) and re-attempts initiate."""
    cache.delete(_key(user_id, key))
