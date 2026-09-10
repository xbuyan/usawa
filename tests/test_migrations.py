"""
Migration regression tests.

fb73997782fe (add email_verified) reached production and failed there —
confirmed for real against Render's Postgres — because it was never
tested against a table with pre-existing rows, only against fresh/empty
databases (which is what running the test suite, or `flask db upgrade`
on a new local dev DB, naturally exercises). Every migration that adds a
NOT NULL column is exactly this same risk, so this file tests that
scenario directly and explicitly for every such migration, not just the
one that already broke once.

Uses subprocess + the actual `flask db upgrade` CLI (not the Python
Alembic API) so this test exercises literally the same command Render's
build step runs, against a real file-based SQLite DB (not the in-memory
DB conftest.py's app fixture uses) so rows genuinely persist between
migration steps the way they do in production.
"""

import os
import subprocess
import sqlite3
import tempfile

import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_flask_db(args, db_path):
    env = {
        **os.environ,
        "SECRET_KEY": "test-key",
        "FLASK_APP": "app.py",
        "DATABASE_URL": f"sqlite:///{db_path}",
    }
    result = subprocess.run(
        ["flask", "db"] + args,
        cwd=PROJECT_DIR, env=env, capture_output=True, text=True,
    )
    return result


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)  # flask db upgrade creates it fresh
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_email_verified_migration_applies_to_table_with_existing_row(temp_db_path):
    # Reproduces the exact production incident: a real user row exists
    # BEFORE this migration runs (matching a live app with real signups),
    # then the migration must apply cleanly, not raise NotNullViolation.
    result = _run_flask_db(["upgrade", "147496921eed"], temp_db_path)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(temp_db_path)
    conn.execute(
        "INSERT INTO users (email, password_hash, organization_name, created_at) "
        "VALUES ('realuser@company.com', 'hash', 'RealCo', '2026-01-01 00:00:00')"
    )
    conn.commit()
    conn.close()

    result = _run_flask_db(["upgrade", "fb73997782fe"], temp_db_path)
    assert result.returncode == 0, (
        f"email_verified migration failed against a table with a "
        f"pre-existing row (this is the exact production incident): "
        f"{result.stderr}"
    )

    conn = sqlite3.connect(temp_db_path)
    row = conn.execute("SELECT email, email_verified FROM users").fetchone()
    conn.close()
    assert row == ("realuser@company.com", 0)  # backfilled to False/0


def test_account_lockout_migration_applies_to_table_with_existing_row(temp_db_path):
    result = _run_flask_db(["upgrade", "fb73997782fe"], temp_db_path)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(temp_db_path)
    conn.execute(
        "INSERT INTO users (email, password_hash, organization_name, email_verified, created_at) "
        "VALUES ('realuser2@company.com', 'hash', 'RealCo', 0, '2026-01-01 00:00:00')"
    )
    conn.commit()
    conn.close()

    result = _run_flask_db(["upgrade", "db74a3830402"], temp_db_path)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(temp_db_path)
    row = conn.execute(
        "SELECT email, failed_login_attempts, locked_until FROM users"
    ).fetchone()
    conn.close()
    assert row == ("realuser2@company.com", 0, None)


def test_full_migration_chain_applies_to_table_with_existing_row_at_every_step(temp_db_path):
    # Belt-and-suspenders: runs the ENTIRE chain from empty to head, with
    # a real row inserted after the very first migration, so every
    # subsequent migration in the chain gets tested against pre-existing
    # data, not just the two known historical trouble spots above.
    result = _run_flask_db(["upgrade", "147496921eed"], temp_db_path)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(temp_db_path)
    conn.execute(
        "INSERT INTO users (email, password_hash, organization_name, created_at) "
        "VALUES ('survivor@company.com', 'hash', 'RealCo', '2026-01-01 00:00:00')"
    )
    conn.commit()
    conn.close()

    result = _run_flask_db(["upgrade", "head"], temp_db_path)
    assert result.returncode == 0, (
        f"Full migration chain failed against a table with a pre-existing "
        f"row: {result.stderr}"
    )

    conn = sqlite3.connect(temp_db_path)
    row = conn.execute("SELECT email FROM users WHERE email = 'survivor@company.com'").fetchone()
    conn.close()
    assert row is not None, "the pre-existing row must survive the entire chain"
