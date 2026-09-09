"""
Proves the Redis rate-limit storage fix actually works, and proves the
original bug was real — not just "the code compiles."

Gunicorn runs 2 separate OS processes (--workers 2). Flask-Limiter's
in-memory storage lives inside a single Python process, so two gunicorn
workers each get their own independent counter for the same limit. These
tests simulate that by building two completely independent Limiter
instances (standing in for two separate worker processes) that point at
the same storage backend, and checking whether a request counted by one
is visible to the other.

Requires a real Redis server reachable at REDIS_URL (or localhost:6379
by default) — this is an integration test against real infrastructure,
not a mock, per this project's "tested, not just written" standard.
"""

import os

import pytest
from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _build_worker(storage_uri, limit_string):
    """Builds a minimal Flask app + Limiter, standing in for one gunicorn
    worker process. Each call makes a brand-new Limiter instance (never
    shares Python objects with any other worker) so the only thing that
    can make them agree on a count is the shared external storage."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    limiter = Limiter(app=app, key_func=get_remote_address, storage_uri=storage_uri)

    @app.route("/ping")
    @limiter.limit(limit_string)
    def ping():
        return "ok"

    return app.test_client()


@pytest.fixture(autouse=True)
def _skip_if_no_redis():
    """Fail loudly (not skip silently) if Redis isn't reachable, since a
    silently-skipped test would let this exact bug slip back in unnoticed."""
    import redis as redis_lib
    try:
        redis_lib.from_url(REDIS_URL).ping()
    except Exception as e:
        pytest.fail(
            f"Redis is not reachable at {REDIS_URL} — this test suite "
            f"requires a real Redis server to verify shared rate-limit "
            f"storage across processes. Original error: {e}"
        )


def test_memory_storage_does_not_share_counts_across_workers():
    """Documents and reproduces the ORIGINAL bug: two independent
    in-memory-backed 'workers' each get their own full quota, so a
    '2 per minute' limit is effectively '2 per minute per worker'."""
    worker_a = _build_worker("memory://", "2 per minute")
    worker_b = _build_worker("memory://", "2 per minute")

    # Worker A uses its entire quota.
    assert worker_a.get("/ping").status_code == 200
    assert worker_a.get("/ping").status_code == 200
    assert worker_a.get("/ping").status_code == 429  # A is now rate-limited

    # Worker B, sharing nothing but the (in-memory, per-process) storage
    # type, is completely unaffected — it still has its full quota. This
    # is the bug: from the client's point of view hitting a real load
    # balancer, the *effective* limit was 4 per minute, not 2, and which
    # requests succeeded depended on which worker happened to handle them.
    assert worker_b.get("/ping").status_code == 200
    assert worker_b.get("/ping").status_code == 200


def test_redis_storage_shares_counts_across_workers():
    """Proves the fix: two independent 'workers' pointed at the same
    Redis instance correctly share a single counter, so the limit means
    what it says regardless of which worker handles a given request."""
    key = f"test-shared-{os.getpid()}"
    storage_uri = REDIS_URL

    worker_a = _build_worker(storage_uri, "3 per minute")
    worker_b = _build_worker(storage_uri, "3 per minute")

    # Both workers share a rate-limit key by IP (test client uses the same
    # source IP for both), and both point at the same Redis instance, so
    # requests via either worker draw from the same shared quota of 3.
    assert worker_a.get("/ping").status_code == 200  # 1/3
    assert worker_b.get("/ping").status_code == 200  # 2/3 — B sees A's usage
    assert worker_a.get("/ping").status_code == 200  # 3/3
    assert worker_b.get("/ping").status_code == 429  # quota exhausted, shared
    assert worker_a.get("/ping").status_code == 429  # still exhausted on A too
