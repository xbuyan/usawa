"""
Org/team sharing — access control tests.

The join onto User.organization_id is what actually delivers "team
sharing": these tests put two users in the SAME organization directly
via the DB (rather than through the invite flow, which lives on a
separate branch) and confirm they can see each other's ClientReport and
AuditLog rows. Cross-ORGANIZATION isolation is already covered by
test_auth.py's test_user_cannot_see_another_users_saved_reports (two
solo signups get distinct orgs automatically) and is deliberately not
duplicated here — this file is specifically about the SAME-org case.
"""

from models import db, User


def _put_in_same_organization(app, email_a, email_b):
    """
    Test-only helper: makes email_b's user share email_a's organization,
    the same end state an accepted invite produces.

    Deliberately does NOT open its own `with app.app_context():` here.
    The pytest `app` fixture already keeps one app context open for the
    whole test (see conftest.py), and Flask reuses that SAME context for
    every test-client call rather than pushing a fresh one per call
    (Flask only pushes a new app context when none is active, or when
    the active one belongs to a different app). A nested app_context
    opened here would get its OWN separate SQLAlchemy session — the
    commit below would land in the database correctly, but the test
    client's NEXT request would keep using the outer context's session,
    whose identity map already cached email_b's User object (from their
    earlier registration call) and would go on returning that stale,
    pre-update object instead of querying again. Operating directly in
    the already-active outer context, then expiring the session's cache
    below, avoids creating that second, disconnected session.
    """
    user_a = User.query.filter_by(email=email_a).first()
    user_b = User.query.filter_by(email=email_b).first()
    user_b.organization_id = user_a.organization_id
    db.session.commit()
    # Belt and suspenders beyond the commit itself: expire_all() forces
    # every already-loaded object in this (shared, long-lived-for-the-
    # test) session — including whatever Flask-Login loads as
    # current_user on the next request — to re-read from the database
    # rather than serve cached attribute values on its next access.
    db.session.expire_all()


def test_teammate_can_see_report_in_list(client, app):
    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "creator@company.com",
        "password": "correcthorsebattery",
    })
    client.post("/api/clients", json={
        "company_name": "Shared Co", "form": {},
        "scorecard": {"overall_score": 70, "sub_scores": {}, "details": {}},
    })
    client.post("/api/auth/logout")

    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "teammate@company.com",
        "password": "correcthorsebattery",
    })
    _put_in_same_organization(app, "creator@company.com", "teammate@company.com")

    resp = client.get("/api/clients")
    assert resp.status_code == 200
    companies = [r["company_name"] for r in resp.get_json()]
    assert "Shared Co" in companies
    # The list identifies whose report it is — this is a shared team
    # view, not an anonymous merge of everyone's data.
    shared = next(r for r in resp.get_json() if r["company_name"] == "Shared Co")
    assert shared["owner_email"] == "creator@company.com"


def test_teammate_can_fetch_report_by_id(client, app):
    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "creator2@company.com",
        "password": "correcthorsebattery",
    })
    save_resp = client.post("/api/clients", json={
        "company_name": "Detail Co", "form": {"a": 1},
        "scorecard": {"overall_score": 61, "sub_scores": {}, "details": {}},
    })
    report_id = save_resp.get_json()["id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "teammate2@company.com",
        "password": "correcthorsebattery",
    })
    _put_in_same_organization(app, "creator2@company.com", "teammate2@company.com")

    resp = client.get(f"/api/clients/{report_id}")
    assert resp.status_code == 200
    assert resp.get_json()["company_name"] == "Detail Co"
    assert resp.get_json()["owner_email"] == "creator2@company.com"


def test_teammate_cannot_delete_someone_elses_report(client, app):
    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "creator3@company.com",
        "password": "correcthorsebattery",
    })
    save_resp = client.post("/api/clients", json={
        "company_name": "Protected Co", "form": {},
        "scorecard": {"overall_score": 50, "sub_scores": {}, "details": {}},
    })
    report_id = save_resp.get_json()["id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "teammate3@company.com",
        "password": "correcthorsebattery",
    })
    _put_in_same_organization(app, "creator3@company.com", "teammate3@company.com")

    delete_resp = client.delete(f"/api/clients/{report_id}")
    assert delete_resp.status_code == 403

    # Still visible afterward — the 403 didn't silently remove it.
    get_resp = client.get(f"/api/clients/{report_id}")
    assert get_resp.status_code == 200


def test_creator_can_still_delete_their_own_report_after_teammate_joins(client, app):
    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "creator4@company.com",
        "password": "correcthorsebattery",
    })
    save_resp = client.post("/api/clients", json={
        "company_name": "Own Deletable Co", "form": {},
        "scorecard": {"overall_score": 50, "sub_scores": {}, "details": {}},
    })
    report_id = save_resp.get_json()["id"]

    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "teammate4@company.com",
        "password": "correcthorsebattery",
    })
    _put_in_same_organization(app, "creator4@company.com", "teammate4@company.com")
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"email": "creator4@company.com", "password": "correcthorsebattery"})
    delete_resp = client.delete(f"/api/clients/{report_id}")
    assert delete_resp.status_code == 204


def test_audit_log_is_visible_org_wide(client, app):
    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "creator5@company.com",
        "password": "correcthorsebattery",
    })
    client.post("/api/clients", json={
        "company_name": "Audited Co", "form": {},
        "scorecard": {"overall_score": 50, "sub_scores": {}, "details": {}},
    })
    client.post("/api/auth/logout")

    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "teammate5@company.com",
        "password": "correcthorsebattery",
    })
    _put_in_same_organization(app, "creator5@company.com", "teammate5@company.com")

    resp = client.get("/api/audit-log")
    assert resp.status_code == 200
    entries = resp.get_json()
    creator_entries = [e for e in entries if e["user_email"] == "creator5@company.com"]
    assert any(e["action"] == "client_report_created" for e in creator_entries)


def test_audit_log_still_excludes_different_organization(client):
    # Two solo signups, no shared org — same isolation guarantee as
    # test_auth.py's report-visibility test, checked here for audit log.
    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "solo-a@company.com",
        "password": "correcthorsebattery",
    })
    client.post("/api/clients", json={
        "company_name": "Solo A Co", "form": {},
        "scorecard": {"overall_score": 50, "sub_scores": {}, "details": {}},
    })
    client.post("/api/auth/logout")

    client.post("/api/auth/register", json={
        "terms_accepted": True, "email": "solo-b@company.com",
        "password": "correcthorsebattery",
    })
    resp = client.get("/api/audit-log")
    entries = resp.get_json()
    assert all(e["user_email"] != "solo-a@company.com" for e in entries)
