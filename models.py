"""
Database models. Uses SQLAlchemy so the same code runs against SQLite
locally (zero setup) and Postgres in production (set DATABASE_URL) without
any code changes — only the connection string differs.
"""

from datetime import datetime, timezone, timedelta

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    organization_name = db.Column(db.String(255), nullable=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Account lockout — rate limiting (see extensions.py) slows brute force
    # by IP, but a distributed/slow attacker can stay under the per-IP
    # limit while still hammering one account. This adds a second,
    # per-account layer: after too many consecutive failures, the account
    # itself is locked for a cooldown window regardless of source IP.
    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_MINUTES = 15

    @staticmethod
    def _utcnow_naive() -> datetime:
        # Plain db.DateTime columns strip tzinfo on write (confirmed via
        # SQLite; Postgres without timezone=True behaves the same way), so
        # a value read back from the DB is always naive. Comparing that
        # against an aware datetime.now(timezone.utc) raises TypeError —
        # this was caught by an actual test, not spotted by inspection.
        # Storing and comparing naive-but-UTC consistently avoids it.
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > self._utcnow_naive()

    def register_failed_login(self) -> None:
        """Call after a wrong-password attempt for this user. Locks the
        account once MAX_FAILED_ATTEMPTS consecutive failures are reached."""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= self.MAX_FAILED_ATTEMPTS:
            self.locked_until = self._utcnow_naive() + timedelta(minutes=self.LOCKOUT_MINUTES)

    def register_successful_login(self) -> None:
        """Call after a correct-password login. Clears the failure count
        and any lock, so a legitimate login fully resets the counter."""
        self.failed_login_attempts = 0
        self.locked_until = None

    reports = db.relationship("ClientReport", backref="owner", lazy=True, cascade="all, delete-orphan")

    def set_password(self, raw_password: str) -> None:
        # scrypt (Werkzeug's default) is a strong, slow-by-design hash —
        # appropriate for password storage, unlike fast hashes like plain SHA256.
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)


class ClientReport(db.Model):
    __tablename__ = "client_reports"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    company_name = db.Column(db.String(255), nullable=False)
    saved_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    form_json = db.Column(db.Text, nullable=False)
    scorecard_json = db.Column(db.Text, nullable=False)
    insights_json = db.Column(db.Text, nullable=True)


class AuditLog(db.Model):
    """
    Durable, queryable record of who accessed or changed sensitive data,
    and when. Distinct from the structured JSON application logs
    (logging_config.py) on purpose: application logs go to stdout and are
    only as durable as whatever log retention the hosting platform gives
    you for free, aren't easily queryable per-user, and — before this —
    didn't cover read access at all (only saves/deletes got a log line).
    A real audit trail for a tool handling pay/demographic data needs to
    survive log rotation and answer "who looked at this client's data,
    and when" directly from the database.

    No cascade delete from User: deliberately, an account deletion
    feature (not yet built) should have to decide explicitly what happens
    to that user's audit trail rather than silently losing it as a side
    effect of an unrelated ORM cascade.
    """
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False, index=True)
    resource_type = db.Column(db.String(64), nullable=True)
    resource_id = db.Column(db.String(64), nullable=True)
    detail = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
