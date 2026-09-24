"""
Auth flow and data isolation tests. Data isolation is the single most
important thing to keep covered here — a regression that lets one user
see another user's saved reports is a serious incident, not a bug ticket.
"""


def test_register_creates_account(client):
    resp = client.post("/api/auth/register", json={"terms_accepted": True,
        "email": "new@example.com", "password": "strongpassword1",
    })
    assert resp.status_code == 201
    assert resp.get_json()["email"] == "new@example.com"


def test_register_rejects_weak_password(client):
    resp = client.post("/api/auth/register", json={"terms_accepted": True,
        "email": "weak@example.com", "password": "short",
    })
    assert resp.status_code == 400


def test_register_rejects_invalid_email(client):
    resp = client.post("/api/auth/register", json={"terms_accepted": True,
        "email": "not-an-email", "password": "strongpassword1",
    })
    assert resp.status_code == 400


def test_register_rejects_duplicate_email(client, registered_user):
    client, email, password = registered_user
    resp = client.post("/api/auth/register", json={"terms_accepted": True,
        "email": email, "password": "differentpassword1",
    })
    assert resp.status_code == 409


def test_login_succeeds_with_correct_password(client, registered_user):
    client, email, password = registered_user
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200


def test_login_rejects_wrong_password(client, registered_user):
    client, email, password = registered_user
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
    assert resp.status_code == 401


def test_login_error_message_identical_for_bad_email_and_bad_password(client, registered_user):
    # Prevents account enumeration — both failure modes must look the same.
    client, email, password = registered_user
    client.post("/api/auth/logout")
    r1 = client.post("/api/auth/login", json={"email": "doesnotexist@example.com", "password": "whatever12"})
    r2 = client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
    assert r1.get_json()["error"] == r2.get_json()["error"]


def test_unauthenticated_api_request_returns_json_401_not_redirect(client):
    resp = client.get("/api/clients")
    assert resp.status_code == 401
    assert resp.get_json()["error"]


def test_unauthenticated_page_request_redirects(client):
    resp = client.get("/app")
    assert resp.status_code == 302


def test_landing_page_is_public(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_user_cannot_see_another_users_saved_reports(client):
    # User A registers and saves a report.
    client.post("/api/auth/register", json={"terms_accepted": True, "email": "a@example.com", "password": "passwordforalice"})
    save_resp = client.post("/api/clients", json={
        "company_name": "Acme Inc",
        "form": {},
        "scorecard": {"overall_score": 72, "sub_scores": {}, "details": {}},
    })
    assert save_resp.status_code == 201
    report_id = save_resp.get_json()["id"]
    client.post("/api/auth/logout")

    # User B registers — a fresh session — and should see nothing of A's.
    client.post("/api/auth/register", json={"terms_accepted": True, "email": "b@example.com", "password": "passwordforbob"})
    list_resp = client.get("/api/clients")
    assert list_resp.get_json() == []

    # User B cannot fetch A's report directly by ID either.
    get_resp = client.get(f"/api/clients/{report_id}")
    assert get_resp.status_code == 404

    # Nor delete it.
    delete_resp = client.delete(f"/api/clients/{report_id}")
    assert delete_resp.status_code == 404


def test_user_can_see_and_delete_their_own_report(client, registered_user):
    client, email, password = registered_user
    save_resp = client.post("/api/clients", json={
        "company_name": "Own Report Co",
        "form": {},
        "scorecard": {"overall_score": 55, "sub_scores": {}, "details": {}},
    })
    report_id = save_resp.get_json()["id"]

    get_resp = client.get(f"/api/clients/{report_id}")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["company_name"] == "Own Report Co"

    delete_resp = client.delete(f"/api/clients/{report_id}")
    assert delete_resp.status_code == 204

    get_after_delete = client.get(f"/api/clients/{report_id}")
    assert get_after_delete.status_code == 404


# ---------------------------------------------------------------------------
# Signup consent (Terms of Service)
# ---------------------------------------------------------------------------

import pytest
from datetime import datetime, timedelta, timezone

from models import User


def _register(client, **overrides):
    body = {"email": "consent@example.com", "password": "strongpassword1"}
    body.update(overrides)
    return client.post("/api/auth/register", json=body)


def test_register_requires_terms_accepted_field(client, app):
    body = {"email": "consent@example.com", "password": "strongpassword1"}
    resp = client.post("/api/auth/register", json=body)
    assert resp.status_code == 400
    fields = [d["field"] for d in resp.get_json()["details"]]
    assert "terms_accepted" in fields
    assert User.query.filter_by(email="consent@example.com").first() is None


def test_register_rejects_terms_accepted_false(client, app):
    resp = _register(client, terms_accepted=False)
    assert resp.status_code == 400
    fields = [d["field"] for d in resp.get_json()["details"]]
    assert "terms_accepted" in fields
    assert User.query.filter_by(email="consent@example.com").first() is None


@pytest.mark.parametrize("sloppy", ["true", "yes", "True", 1, "1", None, [], {}])
def test_register_rejects_truthy_lookalikes_for_terms(client, app, sloppy):
    # Consent must be an explicit JSON `true`. Strings/numbers that merely
    # look truthy must not record consent.
    resp = _register(client, terms_accepted=sloppy)
    assert resp.status_code == 400
    assert User.query.filter_by(email="consent@example.com").first() is None


def test_register_records_terms_accepted_at(client, app):
    before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    resp = _register(client, terms_accepted=True)
    assert resp.status_code == 201
    after = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=5)

    user = User.query.filter_by(email="consent@example.com").first()
    assert user is not None
    assert user.terms_accepted_at is not None
    assert before <= user.terms_accepted_at <= after


def test_rejected_registration_does_not_log_the_user_in(client, app):
    _register(client, terms_accepted=False)
    assert client.get("/api/clients").status_code == 401


def test_terms_page_is_public_and_states_draft_status(client):
    resp = client.get("/terms")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Terms of Service" in html
    assert "not yet been reviewed by legal counsel" in html


def test_register_page_has_terms_checkbox_linking_to_terms(client):
    html = client.get("/register").get_data(as_text=True)
    assert 'id="termsAccepted"' in html
    assert 'href="/terms"' in html
