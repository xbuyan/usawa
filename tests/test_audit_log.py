"""
Audit log tests. Confirms entries are actually written (not just that the
code path doesn't crash) for the access/change events that matter for a
tool handling sensitive pay/demographic data, that a user only ever sees
their own trail, and that the recorded IP address is the real client IP
(via ProxyFix) rather than an internal proxy address.
"""

import io

from models import AuditLog


def _actions_for(client, endpoint="/api/audit-log"):
    resp = client.get(endpoint)
    assert resp.status_code == 200
    return [e["action"] for e in resp.get_json()]


def test_successful_login_is_audited(client, registered_user):
    client, email, password = registered_user
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": email, "password": password})
    assert "login_success" in _actions_for(client)


def test_failed_login_is_audited(client, registered_user):
    client, email, password = registered_user
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": email, "password": "wrong"})
    # Log back in correctly so we're authenticated to read the audit log.
    client.post("/api/auth/login", json={"email": email, "password": password})
    actions = _actions_for(client)
    assert "login_failed" in actions
    assert "login_success" in actions


def test_client_report_create_view_delete_are_all_audited(client, registered_user):
    client, email, password = registered_user

    save_resp = client.post("/api/clients", json={
        "company_name": "Acme Ltd",
        "form": {"note": "test"},
        "scorecard": {"overall_score": 80},
    })
    assert save_resp.status_code == 201
    report_id = save_resp.get_json()["id"]

    client.get(f"/api/clients/{report_id}")
    client.delete(f"/api/clients/{report_id}")

    actions = _actions_for(client)
    assert "client_report_created" in actions
    assert "client_report_viewed" in actions
    assert "client_report_deleted" in actions


def test_csv_upload_is_audited(client, registered_user):
    client, email, password = registered_user
    csv_content = "employee_id,level,group,salary\nE001,IC,a,90000\n"
    client.post(
        "/api/parse/employee",
        data={"file": (io.BytesIO(csv_content.encode()), "employees.csv")},
        content_type="multipart/form-data",
    )
    assert "csv_upload_employee" in _actions_for(client)


def test_audit_log_only_shows_own_entries(client, app):
    from models import db, User

    # First user does some auditable things.
    client.post("/api/auth/register", json={"email": "alice@example.com", "password": "correcthorse1"})
    client.post("/api/clients", json={
        "company_name": "Alice's Client",
        "form": {}, "scorecard": {"overall_score": 50},
    })
    client.post("/api/auth/logout")

    # Second user should never see the first user's audit trail.
    client.post("/api/auth/register", json={"email": "bob@example.com", "password": "correcthorse2"})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "bob@example.com", "password": "correcthorse2"})
    resp = client.get("/api/audit-log")
    assert resp.status_code == 200
    entries = resp.get_json()
    assert all(e["detail"] != "Alice's Client" for e in entries)

    with app.app_context():
        alice = User.query.filter_by(email="alice@example.com").first()
        bob = User.query.filter_by(email="bob@example.com").first()
        alice_entries = AuditLog.query.filter_by(user_id=alice.id).count()
        bob_entries = AuditLog.query.filter_by(user_id=bob.id).count()
        assert alice_entries > 0
        assert bob_entries > 0
        assert alice.id != bob.id


def test_audit_log_requires_login(client):
    resp = client.get("/api/audit-log")
    assert resp.status_code == 401


def test_audit_log_records_real_client_ip_via_proxy_fix(client, registered_user, app):
    # Simulates exactly what happens on Render: the real client's IP
    # arrives in X-Forwarded-For, added by the trusted reverse proxy.
    # Without ProxyFix, request.remote_addr would show the test client's
    # default loopback address regardless of this header — this test
    # would still "pass" in that broken state unless it specifically
    # checks for the forwarded value, so it does.
    client, email, password = registered_user
    fake_client_ip = "203.0.113.42"  # TEST-NET-3, reserved for documentation
    client.post(
        "/api/clients",
        json={"company_name": "IP Test Co", "form": {}, "scorecard": {"overall_score": 10}},
        headers={"X-Forwarded-For": fake_client_ip},
    )
    with app.app_context():
        entry = AuditLog.query.filter_by(action="client_report_created").order_by(AuditLog.id.desc()).first()
        assert entry is not None
        assert entry.ip_address == fake_client_ip
