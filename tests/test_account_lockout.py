"""
Account lockout tests. Rate limiting (see test_rate_limiting.py) slows
brute force by source IP; this is a separate layer that locks a specific
account after repeated wrong-password attempts against it, regardless of
where the attempts come from.
"""

from datetime import datetime, timedelta, timezone

from models import db, User


def test_account_locks_after_max_failed_attempts(client, registered_user):
    client, email, password = registered_user
    client.post("/api/auth/logout")

    for _ in range(User.MAX_FAILED_ATTEMPTS - 1):
        resp = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
        assert resp.status_code == 401

    # The attempt that reaches MAX_FAILED_ATTEMPTS locks the account.
    resp = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
    assert resp.status_code == 401  # this attempt itself is still "wrong password"

    # The NEXT attempt, even with the correct password, is rejected as locked.
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 423
    assert "locked" in resp.get_json()["error"].lower()


def test_correct_password_does_not_count_as_failed_attempt(client, registered_user):
    client, email, password = registered_user
    client.post("/api/auth/logout")

    # Fail a few times, short of the lockout threshold.
    for _ in range(User.MAX_FAILED_ATTEMPTS - 1):
        client.post("/api/auth/login", json={"email": email, "password": "wrong"})

    # Then log in correctly — should succeed and reset the counter.
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200

    client.post("/api/auth/logout")
    user = User.query.filter_by(email=email).first()
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_lockout_expires_after_cooldown(app, client, registered_user):
    client, email, password = registered_user
    client.post("/api/auth/logout")

    for _ in range(User.MAX_FAILED_ATTEMPTS):
        client.post("/api/auth/login", json={"email": email, "password": "wrong"})

    # Confirm it's actually locked right now.
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 423

    # Simulate the cooldown window having passed by moving locked_until
    # into the past directly (avoids a real 15-minute sleep in the test).
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        user.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        db.session.commit()

    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200


def test_nonexistent_account_never_locks_or_leaks_state(client):
    # No user row exists for this email, so there's nothing to lock —
    # confirms repeated attempts against a nonexistent account don't error
    # or behave differently from a single attempt (would otherwise leak
    # account existence through timing/behavior differences).
    for _ in range(User.MAX_FAILED_ATTEMPTS + 2):
        resp = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever"})
        assert resp.status_code == 401
