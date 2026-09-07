"""
Authentication: registration, login, logout. Session-based via Flask-Login.

Security decisions worth knowing about, since this is meant to be a
foundation, not an afterthought:
- Passwords are never stored in plain text — only a salted scrypt hash
  (Werkzeug's generate_password_hash default).
- Login errors don't reveal whether the email or password was wrong
  ("Invalid email or password" for both) — prevents account enumeration.
- A minimum password length is enforced server-side, not just in the
  frontend, since frontend validation can always be bypassed.
- Session cookies are marked httponly and samesite by Flask's defaults;
  SESSION_COOKIE_SECURE is enabled when not in debug mode (see app.py),
  so cookies aren't sent over plain HTTP in production.
"""

import re

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user

from models import db, User

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 10


@auth_bp.route("/login", methods=["GET"])
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return render_template("login.html")


@auth_bp.route("/register", methods=["GET"])
def register_page():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return render_template("register.html")


@auth_bp.route("/api/auth/register", methods=["POST"])
def register():
    body = request.get_json(force=True)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    organization_name = (body.get("organization_name") or "").strip()

    if not EMAIL_RE.match(email):
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(password) < MIN_PASSWORD_LENGTH:
        return jsonify({"error": f"Password must be at least {MIN_PASSWORD_LENGTH} characters."}), 400
    if User.query.filter_by(email=email).first():
        # Intentionally vague-but-honest here (unlike login) since account
        # enumeration risk is lower at registration and a clear message
        # helps a genuine user who forgot they already signed up.
        return jsonify({"error": "An account with this email already exists."}), 409

    user = User(email=email, organization_name=organization_name or None)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    login_user(user)
    return jsonify({"email": user.email}), 201


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    body = request.get_json(force=True)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        # Same message either way — don't reveal whether the email exists.
        return jsonify({"error": "Invalid email or password."}), 401

    login_user(user)
    return jsonify({"email": user.email})


@auth_bp.route("/api/auth/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return "", 204


@auth_bp.route("/api/auth/me", methods=["GET"])
def me():
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False})
    return jsonify({
        "authenticated": True,
        "email": current_user.email,
        "organization_name": current_user.organization_name,
    })
