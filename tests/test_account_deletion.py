"""
Account deletion tests. The mechanics that matter most here aren't the
happy path (any implementation gets that right) — it's whether every row
that references the deleted user actually gets cleaned up, since User
only has an ORM cascade to ClientReport. Conversation and AuditLog rows
are unrelated by cascade on purpose (see models.py / auth.py), so a
regression that forgets to delete them would either orphan rows (SQLite,
which doesn't enforce the FK in these tests) or hard-fail the whole
request (Postgres in production, where the FK is enforced) — either way,
these tests create real rows in both tables and assert they're gone.
"""

from models import db, User, ClientReport, Conversation, ChatMessage, AuditLog


def _add_conversation_and_message(app, user_id):
    with app.app_context():
        convo = Conversation(user_id=user_id, title="Test conversation")
        db.session.add(convo)
        db.session.commit()
        msg = ChatMessage(conversation_id=convo.id, role="user", content="hello")
        db.session.add(msg)
        db.session.commit()
        return convo.id, msg.id


def test_delete_account_requires_login(client):
    resp = client.post("/api/auth/delete-account", json={"password": "whatever"})
    assert resp.status_code == 401


def test_delete_account_rejects_wrong_password(client, registered_user):
    client, email, password = registered_user
    resp = client.post("/api/auth/delete-account", json={"password": "definitely-wrong"})
    assert resp.status_code == 401
    assert "password" in resp.get_json()["error"].lower()

    # Account must still exist and be usable.
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200


def test_delete_account_requires_password_field(client, registered_user):
    client, email, password = registered_user
    resp = client.post("/api/auth/delete-account", json={})
    assert resp.status_code == 400


def test_delete_account_happy_path_logs_out_and_removes_user(client, registered_user, app):
    client, email, password = registered_user
    with app.app_context():
        user_id = User.query.filter_by(email=email).first().id

    resp = client.post("/api/auth/delete-account", json={"password": password})
    assert resp.status_code == 204

    # Session is dead — /api/auth/me (200 either way, by design) now
    # reports no one is logged in.
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.get_json()["authenticated"] is False

    with app.app_context():
        assert db.session.get(User, user_id) is None


def test_delete_account_removes_client_reports(client, registered_user, app):
    client, email, password = registered_user
    client.post("/api/clients", json={
        "company_name": "Acme Ltd",
        "form": {}, "scorecard": {"overall_score": 80},
    })

    with app.app_context():
        user_id = User.query.filter_by(email=email).first().id
        assert ClientReport.query.filter_by(user_id=user_id).count() == 1

    resp = client.post("/api/auth/delete-account", json={"password": password})
    assert resp.status_code == 204

    with app.app_context():
        assert ClientReport.query.filter_by(user_id=user_id).count() == 0


def test_delete_account_removes_conversations_and_messages(client, registered_user, app):
    client, email, password = registered_user
    with app.app_context():
        user_id = User.query.filter_by(email=email).first().id
    convo_id, msg_id = _add_conversation_and_message(app, user_id)

    resp = client.post("/api/auth/delete-account", json={"password": password})
    assert resp.status_code == 204

    with app.app_context():
        assert db.session.get(Conversation, convo_id) is None
        assert db.session.get(ChatMessage, msg_id) is None


def test_delete_account_removes_this_users_audit_log(client, registered_user, app):
    client, email, password = registered_user
    # Registration itself doesn't write an AuditLog row (only explicit
    # events like login/report actions do) — generate one deliberately.
    client.post("/api/clients", json={
        "company_name": "Acme Ltd", "form": {}, "scorecard": {"overall_score": 80},
    })
    with app.app_context():
        user_id = User.query.filter_by(email=email).first().id
        assert AuditLog.query.filter_by(user_id=user_id).count() > 0

    resp = client.post("/api/auth/delete-account", json={"password": password})
    assert resp.status_code == 204

    with app.app_context():
        assert AuditLog.query.filter_by(user_id=user_id).count() == 0


def test_delete_account_does_not_affect_other_users(client, app):
    client.post("/api/auth/register", json={
        "email": "keep@example.com", "password": "correcthorsebattery",
        "organization_name": "Keep Co", "terms_accepted": True,
    })
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={
        "email": "delete-me@example.com", "password": "correcthorsebattery",
        "organization_name": "Gone Co", "terms_accepted": True,
    })

    resp = client.post("/api/auth/delete-account", json={"password": "correcthorsebattery"})
    assert resp.status_code == 204

    with app.app_context():
        assert User.query.filter_by(email="keep@example.com").first() is not None
        assert User.query.filter_by(email="delete-me@example.com").first() is None


# Note: this route carries @limiter.limit("5 per hour"), matching the
# handoff doc's design. It isn't exercised here because the app disables
# Flask-Limiter under TESTING (see app.py) — same as every other
# rate-limited route in this codebase (register, login, insights, chat).
# Real rate-limit-firing behavior is covered separately, against real
# Redis, in test_rate_limiting.py.
