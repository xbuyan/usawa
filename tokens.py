"""
Stateless tokens for password reset and email verification.

Uses itsdangerous (already a Flask/Werkzeug dependency, no new package
needed) to create signed, expiring tokens without a database table to
track them. Two different "salts" keep a reset token from being replayable
as a verification token or vice versa, even though both are signed with
the same SECRET_KEY.

Password reset tokens embed a fingerprint of the CURRENT password hash.
When the password actually gets reset, the hash changes, so the fingerprint
in any old token (including the one just used) no longer matches — that's
what makes a reset token single-use without needing to store "used" tokens
in a database.
"""

import hashlib

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

RESET_PASSWORD_SALT = "usawa-password-reset"
VERIFY_EMAIL_SALT = "usawa-email-verify"

RESET_PASSWORD_MAX_AGE_SECONDS = 60 * 60  # 1 hour
VERIFY_EMAIL_MAX_AGE_SECONDS = 60 * 60 * 24 * 3  # 3 days


def _serializer(secret_key: str, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt=salt)


def _password_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def generate_reset_token(secret_key: str, user) -> str:
    s = _serializer(secret_key, RESET_PASSWORD_SALT)
    return s.dumps({
        "user_id": user.id,
        "pw_fingerprint": _password_fingerprint(user.password_hash),
    })


def verify_reset_token(secret_key: str, token: str, user_lookup):
    """
    user_lookup: callable(user_id) -> User or None.
    Returns (user, error_message). user is None if invalid/expired/already-used.
    """
    s = _serializer(secret_key, RESET_PASSWORD_SALT)
    try:
        data = s.loads(token, max_age=RESET_PASSWORD_MAX_AGE_SECONDS)
    except SignatureExpired:
        return None, "This reset link has expired. Request a new one."
    except BadSignature:
        return None, "This reset link is invalid."

    user = user_lookup(data.get("user_id"))
    if not user:
        return None, "This reset link is invalid."

    if _password_fingerprint(user.password_hash) != data.get("pw_fingerprint"):
        # Password already changed since this token was issued — either it
        # was already used, or a newer reset request superseded it.
        return None, "This reset link has already been used. Request a new one."

    return user, None


def generate_verify_email_token(secret_key: str, user) -> str:
    s = _serializer(secret_key, VERIFY_EMAIL_SALT)
    return s.dumps({"user_id": user.id, "email": user.email})


def verify_email_token(secret_key: str, token: str, user_lookup):
    s = _serializer(secret_key, VERIFY_EMAIL_SALT)
    try:
        data = s.loads(token, max_age=VERIFY_EMAIL_MAX_AGE_SECONDS)
    except SignatureExpired:
        return None, "This verification link has expired. Request a new one."
    except BadSignature:
        return None, "This verification link is invalid."

    user = user_lookup(data.get("user_id"))
    if not user or user.email != data.get("email"):
        return None, "This verification link is invalid."

    return user, None
