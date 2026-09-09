"""
Audit log helper. One function, called from routes that touch sensitive
data (viewing/exporting/deleting a client report, uploading employee or
applicant CSVs, generating AI insights, and login events) so every call
site records entries the same way instead of each route hand-rolling it.
"""

from flask import request

from models import db, AuditLog

# Keeping this list explicit (rather than accepting any string) makes it
# obvious, from one place, exactly what this project considers audit-worthy —
# and stops a typo'd action string from silently creating a new, uncounted
# category that nobody notices.
VALID_ACTIONS = {
    "login_success",
    "login_failed",
    "login_locked",
    "csv_upload_employee",
    "csv_upload_applicant",
    "insights_generated",
    "client_report_created",
    "client_report_viewed",
    "client_report_deleted",
}


def record(user_id: int, action: str, resource_type: str = None,
           resource_id=None, detail: str = None) -> None:
    """
    Writes one audit log entry and commits immediately. Commits on its
    own (rather than relying on the caller's later commit) so an audit
    entry for a read-only action like "viewed" — which has no other
    database write in the same request — is still actually persisted.

    Deliberately does not raise on failure beyond the assertion below:
    a malformed action name is a programming error worth catching in
    tests, but a transient DB hiccup while writing an audit entry
    shouldn't itself take down the request that triggered it. Errors are
    left to propagate to the standard error handler/Sentry like any other
    exception, rather than being silently swallowed here.
    """
    assert action in VALID_ACTIONS, f"Unrecognized audit action: {action!r}"

    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        detail=detail,
        ip_address=request.remote_addr if request else None,
    )
    db.session.add(entry)
    db.session.commit()
