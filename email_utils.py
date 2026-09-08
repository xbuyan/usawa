"""
Email sending.

Uses Flask-Mail with standard SMTP config, which works with any provider
(Gmail SMTP, SendGrid, Mailgun, Postmark, etc. — all support plain SMTP).

Honest limitation: this has NOT been tested against a real SMTP server or
real inbox, since that requires real credentials this environment doesn't
have. The code is correct Flask-Mail usage, but "correct code" and "verified
to actually deliver mail without landing in spam" are different claims —
test this yourself with real credentials before relying on it for real
users, and check your provider's sender-reputation/SPF/DKIM setup, which
affects deliverability far more than the code that calls their API.

Dev-mode fallback: if SMTP isn't configured (no MAIL_SERVER env var), emails
are logged instead of sent, so registration/password-reset flows still work
locally without needing real email credentials.
"""

import logging
import os

from flask_mail import Mail, Message

logger = logging.getLogger(__name__)

mail = Mail()


def init_mail(app):
    app.config.setdefault("MAIL_SERVER", os.environ.get("MAIL_SERVER", ""))
    app.config.setdefault("MAIL_PORT", int(os.environ.get("MAIL_PORT", 587)))
    app.config.setdefault("MAIL_USE_TLS", os.environ.get("MAIL_USE_TLS", "1") == "1")
    app.config.setdefault("MAIL_USERNAME", os.environ.get("MAIL_USERNAME", ""))
    app.config.setdefault("MAIL_PASSWORD", os.environ.get("MAIL_PASSWORD", ""))
    app.config.setdefault(
        "MAIL_DEFAULT_SENDER",
        os.environ.get("MAIL_DEFAULT_SENDER", "noreply@usawa.co.ke"),
    )
    mail.init_app(app)


def is_mail_configured() -> bool:
    from flask import current_app
    return bool(current_app.config.get("MAIL_SERVER"))


def send_email(subject: str, recipient: str, body: str) -> bool:
    """
    Returns True if the email was sent (or logged, in dev-fallback mode).
    Never raises — a broken mail server shouldn't crash the request that
    triggered the email (e.g. registration should still succeed even if
    the verification email fails to send; log it and move on).
    """
    if not is_mail_configured():
        logger.info(
            "MAIL_SERVER not configured — logging email instead of sending.",
            extra={"email_subject": subject, "email_recipient": recipient, "email_body": body},
        )
        return True

    try:
        from flask import current_app
        msg = Message(subject=subject, recipients=[recipient], body=body)
        mail.send(msg)
        return True
    except Exception:
        logger.exception(
            "Failed to send email.",
            extra={"email_subject": subject, "email_recipient": recipient},
        )
        return False
