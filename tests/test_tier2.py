"""
Tests for the Tier 2 additions: password reset, email verification tokens,
and Pydantic request validation.
"""

import time

from tokens import (
    generate_reset_token, verify_reset_token,
    generate_verify_email_token, verify_email_token,
)
from models import User, db


def test_forgot_password_returns_same_message_for_existing_and_missing_email(client, registered_user):
    client, email, password = registered_user
    r1 = client.post("/api/auth/forgot-password", json={"email": email})
    r2 = client.post("/api/auth/forgot-password", json={"email": "doesnotexist@example.com"})
    assert r1.get_json()["message"] == r2.get_json()["message"]


def test_reset_token_round_trip(app, registered_user):
    client, email, password = registered_user
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        token = generate_reset_token(app.config["SECRET_KEY"], user)
        found_user, error = verify_reset_token(
            app.config["SECRET_KEY"], token, lambda uid: db.session.get(User, uid)
        )
        assert error is None
        assert found_user.email == email


def test_reset_token_cannot_be_reused_after_password_changes(app, registered_user):
    client, email, password = registered_user
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        token = generate_reset_token(app.config["SECRET_KEY"], user)

        # Simulate the password actually changing.
        user.set_password("aBrandNewPassword123")
        db.session.commit()

        found_user, error = verify_reset_token(
            app.config["SECRET_KEY"], token, lambda uid: db.session.get(User, uid)
        )
        assert found_user is None
        assert "already been used" in error


def test_reset_password_endpoint_end_to_end(app, registered_user):
    client, email, password = registered_user
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        token = generate_reset_token(app.config["SECRET_KEY"], user)

    resp = client.post("/api/auth/reset-password", json={
        "token": token, "new_password": "aCompletelyNewPassword1",
    })
    assert resp.status_code == 200

    # Old password should no longer work.
    client.post("/api/auth/logout")
    old_login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert old_login.status_code == 401

    # New password should work.
    new_login = client.post("/api/auth/login", json={
        "email": email, "password": "aCompletelyNewPassword1",
    })
    assert new_login.status_code == 200


def test_reset_password_rejects_invalid_token(client):
    resp = client.post("/api/auth/reset-password", json={
        "token": "not-a-real-token", "new_password": "somepassword1",
    })
    assert resp.status_code == 400


def test_verify_email_token_round_trip(app, registered_user):
    client, email, password = registered_user
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user.email_verified is False
        token = generate_verify_email_token(app.config["SECRET_KEY"], user)
        found_user, error = verify_email_token(
            app.config["SECRET_KEY"], token, lambda uid: db.session.get(User, uid)
        )
        assert error is None
        assert found_user.email == email


def test_verify_email_endpoint_marks_user_verified(app, registered_user):
    client, email, password = registered_user
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        token = generate_verify_email_token(app.config["SECRET_KEY"], user)

    resp = client.get(f"/verify-email?token={token}")
    assert resp.status_code == 200

    me_resp = client.get("/api/auth/me")
    assert me_resp.get_json()["email_verified"] is True


def test_new_user_starts_unverified(client, registered_user):
    client, email, password = registered_user
    resp = client.get("/api/auth/me")
    assert resp.get_json()["email_verified"] is False


# --- Pydantic validation tests ---------------------------------------------

def test_score_endpoint_rejects_negative_promotion_counts(client, registered_user):
    client, email, password = registered_user
    resp = client.post("/api/score", json={
        "promotion": {"promotions_a": -5, "eligible_a": 10, "promotions_b": 2, "eligible_b": 10},
    })
    assert resp.status_code == 400
    assert resp.get_json()["details"]


def test_register_validation_error_includes_field_name(client):
    resp = client.post("/api/auth/register", json={"email": "not-an-email", "password": "short"})
    assert resp.status_code == 400
    details = resp.get_json()["details"]
    fields = [d["field"] for d in details]
    assert "email" in fields
    assert "password" in fields


def test_save_client_rejects_wrong_types(client, registered_user):
    client, email, password = registered_user
    resp = client.post("/api/clients", json={
        "company_name": 12345,  # should be a string
        "form": "not-a-dict",
    })
    assert resp.status_code == 400
