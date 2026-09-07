"""
Database models. Uses SQLAlchemy so the same code runs against SQLite
locally (zero setup) and Postgres in production (set DATABASE_URL) without
any code changes — only the connection string differs.
"""

from datetime import datetime, timezone

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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

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
