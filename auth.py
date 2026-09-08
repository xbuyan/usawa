"""
Authentication: registration, login, logout, password reset, email
verification. Session-based via Flask-Login.

Security decisions worth knowing about:
- Passwords are never stored in plain text — only a salted scrypt hash
  (Werkzeug's generate_password_hash default).
- Login errors don't reveal whether the email or password was wrong
  ("Invalid email or password" for both) — prevents account enumeration.
- Forgot-password always returns the same success message whether or not
  the email exists — same enumeration protection, applied to the reset flow.
- A minimum password length is enforced server-side via Pydantic, not just
  in the frontend, since frontend validation can always be bypassed.
- Session cookies are httponly and samesite by Flask's defaults;
  SESSION_COOKIE_SECURE is enabled when not in debug mode.
- Email verification is tracked but NOT enforced (login/tool access still
  works for unverified users) — see README for why this is a deliberate
  choice, not an oversight.
"""

import logging

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, current_app
from flask_login import login_user, logout_user, login_required, current_user
from pydantic import ValidationError

from models import db, User
from extensions import limiter
from tokens import (
    generate_reset_token, verify_reset_token,
    generate_verify_email_token, verify_email_token,
)
from email_utils import send_email
from schemas import (
    RegisterRequest, LoginRequest, ForgotPasswordRequest, ResetPasswordRequest,
    validation_error_response,
)

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

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


@auth_bp.route("/forgot-password", methods=["GET"])
def forgot_password_page():
    return render_template("forgot_password.html")


@auth_bp.route("/reset-password", methods=["GET"])
def reset_password_page():
    return render_template("reset_password.html", token=request.args.get("token", ""))


# ---------------------------------------------------------------------------
# Registration / login / logout
# ---------------------------------------------------------------------------

@auth_bp.route("/api/auth/register", methods=["POST"])
@limiter.limit("10 per hour")
def register():
    try:
        body = RegisterRequest.model_validate(request.get_json(force=True) or {})
    except ValidationError as e:
        return jsonify(validation_error_response(e)), 400

    email = body.email.lower()

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists."}), 409

    user = User(email=email, organization_name=body.organization_name or None)
    user.set_password(body.password)
    db.session.add(user)
    db.session.commit()

    login_user(user)

    token = generate_verify_email_token(current_app.config["SECRET_KEY"], user)
    verify_url = url_for("auth.verify_email", token=token, _external=True)
    send_email(
        subject="Verify your Usawa account",
        recipient=user.email,
        body=(
            f"Welcome to Usawa.\n\n"
            f"Verify your email address:\n{verify_url}\n\n"
            f"This link expires in 3 days."
        ),
    )

    return jsonify({"email": user.email}), 201


@auth_bp.route("/api/auth/login", methods=["POST"])
@limiter.limit("15 per hour")
def login():
    try:
        body = LoginRequest.model_validate(request.get_json(force=True) or {})
    except ValidationError as e:
        return jsonify(validation_error_response(e)), 400

    email = body.email.lower()
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(body.password):
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
        "email_verified": current_user.email_verified,
    })


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

@auth_bp.route("/verify-email", methods=["GET"])
def verify_email():
    token = request.args.get("token", "")
    user, error = verify_email_token(
        current_app.config["SECRET_KEY"], token,
        lambda uid: db.session.get(User, uid) if uid else None,
    )
    if error:
        return render_template("message.html", title="Verification failed", message=error, is_error=True)

    user.email_verified = True
    db.session.commit()
    return render_template(
        "message.html",
        title="Email verified",
        message="Your email has been verified. You're all set.",
        is_error=False,
        cta_href="/app",
        cta_label="Go to Usawa",
    )


@auth_bp.route("/api/auth/resend-verification", methods=["POST"])
@login_required
@limiter.limit("5 per hour")
def resend_verification():
    if current_user.email_verified:
        return jsonify({"message": "Already verified."})

    token = generate_verify_email_token(current_app.config["SECRET_KEY"], current_user)
    verify_url = url_for("auth.verify_email", token=token, _external=True)
    sent = send_email(
        subject="Verify your Usawa account",
        recipient=current_user.email,
        body=f"Verify your email address:\n{verify_url}\n\nThis link expires in 3 days.",
    )
    if not sent:
        return jsonify({"error": "Couldn't send the verification email. Try again shortly."}), 502
    return jsonify({"message": "Verification email sent."})


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

@auth_bp.route("/api/auth/forgot-password", methods=["POST"])
@limiter.limit("5 per hour")
def forgot_password():
    try:
        body = ForgotPasswordRequest.model_validate(request.get_json(force=True) or {})
    except ValidationError as e:
        return jsonify(validation_error_response(e)), 400

    email = body.email.lower()
    user = User.query.filter_by(email=email).first()

    # Always the same response whether or not the account exists — the
    # enumeration protection only works if both cases look identical.
    generic_response = jsonify({
        "message": "If an account with that email exists, we've sent a password reset link."
    })

    if not user:
        return generic_response

    token = generate_reset_token(current_app.config["SECRET_KEY"], user)
    reset_url = url_for("auth.reset_password_page", token=token, _external=True)
    send_email(
        subject="Reset your Usawa password",
        recipient=user.email,
        body=(
            f"Reset your password:\n{reset_url}\n\n"
            f"This link expires in 1 hour. If you didn't request this, ignore this email."
        ),
    )
    return generic_response


@auth_bp.route("/api/auth/reset-password", methods=["POST"])
@limiter.limit("10 per hour")
def reset_password():
    try:
        body = ResetPasswordRequest.model_validate(request.get_json(force=True) or {})
    except ValidationError as e:
        return jsonify(validation_error_response(e)), 400

    user, error = verify_reset_token(
        current_app.config["SECRET_KEY"], body.token,
        lambda uid: db.session.get(User, uid) if uid else None,
    )
    if error:
        return jsonify({"error": error}), 400

    user.set_password(body.new_password)
    db.session.commit()
    logger.info("Password reset completed.", extra={"user_id": user.id})

    return jsonify({"message": "Password updated. You can log in now."})
