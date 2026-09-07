"""
Shared pytest fixtures. Every test gets a fresh Flask app instance backed
by an in-memory SQLite database — completely isolated from whatever's
running in local dev or production, and from other tests.
"""

import os

# app.py creates a module-level `app` instance at import time (needed for
# gunicorn/`flask` CLI), which requires SECRET_KEY to be set even before
# pytest fixtures run. This only affects that one-time import-time
# instance — the real per-test app comes from create_app() in the fixture
# below, with its own isolated config.
os.environ.setdefault("SECRET_KEY", "test-secret-for-pytest-collection")

import pytest
from app import create_app
from models import db as _db


@pytest.fixture
def app():
    application = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,  # tests exercise business logic, not CSRF plumbing
        "SECRET_KEY": "test-secret",
    })
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def registered_user(client):
    """Registers a user and returns (client, email, password) with the
    session cookie already set on `client` from the registration response."""
    email = "alice@example.com"
    password = "correcthorsebattery"
    client.post("/api/auth/register", json={
        "email": email, "password": password, "organization_name": "Alice Corp",
    })
    return client, email, password
