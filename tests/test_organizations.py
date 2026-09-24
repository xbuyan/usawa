"""
Org/team sharing — signup slice. Every user must belong to exactly one
Organization (organization_id is NOT NULL; see migration a3f8b1c92d47
for the historical-user backfill). This file covers the app-level half
of that guarantee: a fresh signup gets its own new Organization, with a
sensible name either way. Invite/join and the access-control join onto
Organization for ClientReport/AuditLog land in later slices.
"""

from models import db, User, Organization


def test_register_creates_an_organization(client, app):
    resp = client.post("/api/auth/register", json={
        "terms_accepted": True,
        "email": "solo@example.com", "password": "strongpassword1",
        "organization_name": "Solo Corp",
    })
    assert resp.status_code == 201

    with app.app_context():
        user = User.query.filter_by(email="solo@example.com").first()
        assert user.organization_id is not None
        org = db.session.get(Organization, user.organization_id)
        assert org is not None
        assert org.name == "Solo Corp"


def test_register_without_organization_name_still_gets_a_named_organization(client, app):
    resp = client.post("/api/auth/register", json={
        "terms_accepted": True,
        "email": "noorg@example.com", "password": "strongpassword1",
    })
    assert resp.status_code == 201

    with app.app_context():
        user = User.query.filter_by(email="noorg@example.com").first()
        org = db.session.get(Organization, user.organization_id)
        # A name derived from the email, not a bare "Untitled" — same
        # fallback the historical-user backfill migration uses, so the
        # two paths that create an Organization behave consistently.
        assert org.name == "noorg@example.com's organization"


def test_two_solo_signups_get_two_distinct_organizations(client, app):
    client.post("/api/auth/register", json={
        "terms_accepted": True,
        "email": "first@example.com", "password": "strongpassword1",
    })
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={
        "terms_accepted": True,
        "email": "second@example.com", "password": "strongpassword1",
    })

    with app.app_context():
        first = User.query.filter_by(email="first@example.com").first()
        second = User.query.filter_by(email="second@example.com").first()
        assert first.organization_id != second.organization_id
        assert Organization.query.count() == 2
