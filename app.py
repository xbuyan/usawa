"""
Usawa (equity scorecard) — Flask backend

Routes:
  GET  /                        -> public landing page
  GET  /app                     -> the tool (requires login)
  GET  /login, /register        -> auth pages
  GET  /forgot-password, /reset-password -> password reset pages
  GET  /verify-email            -> email verification landing
  POST /api/auth/register       -> create account
  POST /api/auth/login          -> log in
  POST /api/auth/logout         -> log out
  GET  /api/auth/me             -> current session info
  POST /api/auth/forgot-password, /api/auth/reset-password
  POST /api/auth/resend-verification
  POST /api/parse/employee      -> upload employee CSV, returns aggregated metrics
  POST /api/parse/applicant     -> upload applicant CSV, returns aggregated metrics
  POST /api/score               -> run calculate_scorecard() on submitted data
  POST /api/insights            -> generate AI insights for a scorecard
  GET  /api/clients             -> list the current user's saved client reports
  POST /api/clients             -> save a client report (owned by current user)
  GET  /api/clients/<id>        -> fetch one saved report (must be owner)
  DELETE /api/clients/<id>      -> delete a saved report (must be owner)
  GET  /healthz                 -> uptime monitoring target

Run locally (SQLite, zero setup):
  pip install -r requirements.txt
  export ANTHROPIC_API_KEY=your_key_here
  export SECRET_KEY=any-random-string-for-local-dev
  python app.py
  # then open http://localhost:5000

Run in production (Postgres):
  Set DATABASE_URL to a postgres:// connection string and SECRET_KEY to a
  real random secret. Same code, no changes needed — see README.md.

Architecture note: this uses the Flask "application factory" pattern
(create_app()) rather than a module-level app instance. This is what makes
the automated test suite possible — tests build a fresh, isolated app
instance with its own in-memory database instead of sharing global state
with whatever's running in production.
"""

import os
import csv
import io
import json
import logging

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from flask import Flask, request, jsonify, render_template
from flask_login import LoginManager, login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_talisman import Talisman
from flask_migrate import Migrate
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from models import db, User, ClientReport
from extensions import limiter
from dei_scorecard import calculate_scorecard
from csv_aggregation import aggregate_employee_rows, aggregate_applicant_rows
from ai_insights import generate_insights, InsightsGenerationError
from auth import auth_bp
from email_utils import init_mail
from logging_config import configure_logging
from schemas import ScoreRequest, InsightsRequest, SaveClientRequest, validation_error_response

# Sane upper bound on how many rows we'll process from an uploaded CSV.
# Defense in depth alongside MAX_CONTENT_LENGTH: a file could be small in
# bytes but pathological in row count (e.g. mostly empty columns). Real
# bulk imports beyond this size should go through a different path, not
# a browser file upload.
MAX_CSV_ROWS = 20_000

migrate = Migrate()
csrf = CSRFProtect()


def create_app(config_overrides=None):
    app = Flask(__name__)

    # --- Configuration ---------------------------------------------------
    secret_key = os.environ.get("SECRET_KEY")
    is_debug = os.environ.get("FLASK_DEBUG") == "1"
    is_testing = bool(config_overrides and config_overrides.get("TESTING"))

    if not secret_key:
        if is_debug or is_testing:
            secret_key = "dev-only-insecure-key-do-not-use-in-production"
        else:
            raise RuntimeError(
                "SECRET_KEY environment variable is not set. Generate one with "
                "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
                "and set it before running in production."
            )
    app.config["SECRET_KEY"] = secret_key

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url or (
        "sqlite:///" + os.path.join(os.path.dirname(__file__), "usawa.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Cookie hardening
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = not is_debug and not is_testing

    # Hard cap on total request size (covers CSV uploads and any JSON body) —
    # prevents someone from sending a multi-GB payload to degrade the server.
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

    if config_overrides:
        app.config.update(config_overrides)

    # --- Structured logging ---------------------------------------------
    logger = configure_logging(app)

    # --- Error monitoring (Sentry) ---------------------------------------
    # Only activates if SENTRY_DSN is set — silently does nothing otherwise,
    # so this is safe to leave in place before you have a Sentry project.
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if sentry_dsn and not is_testing:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.1,
            environment="production" if not is_debug else "development",
        )
        logger.info("Sentry error monitoring initialized.")

    db.init_app(app)
    migrate.init_app(app, db)
    init_mail(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login_page"

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not logged in."}), 401
        from flask import redirect, url_for
        return redirect(url_for("auth.login_page"))

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # --- CSRF protection ---------------------------------------------------
    csrf.init_app(app)
    app.jinja_env.globals["csrf_token"] = generate_csrf
    if config_overrides and config_overrides.get("WTF_CSRF_ENABLED") is False:
        app.config["WTF_CSRF_ENABLED"] = False

    # --- Rate limiting -------------------------------------------------
    # NOTE: default in-memory storage only works correctly with a single
    # process. Running more than one gunicorn worker in production means
    # each worker tracks its own separate counts — the effective limit
    # becomes (limit x worker count), not a shared limit. Move to a Redis
    # storage backend (storage_uri="redis://...") before scaling past one
    # worker, or the numbers below won't mean what they say.
    limiter.init_app(app)
    if is_testing:
        limiter.enabled = False

    # --- Security headers -----------------------------------------------
    # unsafe-inline is kept for style-src because the templates use inline
    # style="" attributes throughout (a real trade-off, not an oversight —
    # removing it means refactoring every inline style to a class first).
    # script-src does NOT allow unsafe-inline: all page JS lives in static
    # files specifically so this can stay strict.
    csp = {
        "default-src": "'self'",
        "style-src": ["'self'", "https://fonts.googleapis.com", "'unsafe-inline'"],
        "font-src": ["'self'", "https://fonts.gstatic.com"],
        "script-src": ["'self'", "https://cdnjs.cloudflare.com"],
        "img-src": ["'self'", "data:"],
    }
    # force_https is intentionally NOT enabled here even in production.
    # Render (and most PaaS hosts) terminates TLS at a proxy in front of the
    # app and forwards plain HTTP internally — forcing an internal redirect
    # to HTTPS at the Flask layer causes a redirect loop in that setup. The
    # public URL is HTTPS-only regardless because the platform enforces it.
    # HSTS is still sent so browsers remember to prefer HTTPS on repeat visits.
    Talisman(
        app,
        content_security_policy=csp,
        force_https=False,
        strict_transport_security=not (is_debug or is_testing),
    )

    app.register_blueprint(auth_bp)

    @app.errorhandler(Exception)
    def handle_any_error(e):
        """
        Ensures every error response is JSON, never Flask's default HTML
        error page — otherwise the frontend's response.json() call fails
        with a confusing "Unexpected token '<'" error instead of a real
        message. Also where CSRFError and 413 (payload too large) land,
        since both are HTTPException subclasses.
        """
        if isinstance(e, HTTPException):
            return jsonify({"error": e.description}), e.code
        logger.exception("Unhandled exception.", extra={"path": request.path, "method": request.method})
        if sentry_dsn:
            sentry_sdk.capture_exception(e)
        message = str(e) or "An unexpected server error occurred."
        return jsonify({"error": message}), 500

    def read_csv_upload(file_storage):
        """Reads an uploaded CSV file into a list of dicts, capped at MAX_CSV_ROWS."""
        text = file_storage.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for i, row in enumerate(reader):
            if i >= MAX_CSV_ROWS:
                raise ValueError(
                    f"This file has more than {MAX_CSV_ROWS:,} rows. "
                    f"Split it into smaller files, or contact us about bulk imports."
                )
            rows.append(row)
        return rows

    # -----------------------------------------------------------------
    # Frontend
    # -----------------------------------------------------------------

    @app.route("/")
    def landing():
        return render_template("landing.html")

    @app.route("/app")
    @login_required
    def index():
        return render_template("index.html")

    # -----------------------------------------------------------------
    # CSV parsing endpoints
    # -----------------------------------------------------------------

    @app.route("/api/parse/employee", methods=["POST"])
    @login_required
    @limiter.limit("30 per hour")
    def parse_employee_csv():
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded."}), 400
        try:
            rows = read_csv_upload(request.files["file"])
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if not rows:
            return jsonify({"error": "The CSV appears to be empty."}), 400
        result = aggregate_employee_rows(rows)
        return jsonify(result)

    @app.route("/api/parse/applicant", methods=["POST"])
    @login_required
    @limiter.limit("30 per hour")
    def parse_applicant_csv():
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded."}), 400
        try:
            rows = read_csv_upload(request.files["file"])
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if not rows:
            return jsonify({"error": "The CSV appears to be empty."}), 400
        result = aggregate_applicant_rows(rows)
        return jsonify(result)

    # -----------------------------------------------------------------
    # Scoring + insights
    # -----------------------------------------------------------------

    @app.route("/api/score", methods=["POST"])
    @login_required
    def score():
        try:
            body = ScoreRequest.model_validate(request.get_json(force=True) or {})
        except ValidationError as e:
            return jsonify(validation_error_response(e)), 400

        company_data = body.model_dump(exclude_none=True)
        if not company_data:
            return jsonify({"error": "No data submitted."}), 400
        result = calculate_scorecard(company_data)
        return jsonify(result)

    @app.route("/api/insights", methods=["POST"])
    @login_required
    @limiter.limit("30 per hour")  # this call costs real money per request
    def insights():
        try:
            body = InsightsRequest.model_validate(request.get_json(force=True) or {})
        except ValidationError as e:
            return jsonify(validation_error_response(e)), 400

        try:
            result = generate_insights(
                body.scorecard,
                company_size=body.company_size,
                industry=body.industry,
                benchmarks=body.benchmarks,
            )
            return jsonify(result)
        except InsightsGenerationError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            logger.exception("AI insights call failed.")
            if sentry_dsn:
                sentry_sdk.capture_exception(e)
            return jsonify({"error": f"AI insights failed: {e}"}), 502

    # -----------------------------------------------------------------
    # Saved clients — every query scoped to current_user
    # -----------------------------------------------------------------

    @app.route("/api/clients", methods=["GET"])
    @login_required
    def list_clients():
        reports = (
            ClientReport.query.filter_by(user_id=current_user.id)
            .order_by(ClientReport.saved_at.desc())
            .all()
        )
        results = []
        for r in reports:
            scorecard = json.loads(r.scorecard_json)
            results.append({
                "id": r.id,
                "company_name": r.company_name,
                "saved_at": r.saved_at.isoformat(),
                "overall_score": scorecard.get("overall_score"),
            })
        return jsonify(results)

    @app.route("/api/clients", methods=["POST"])
    @login_required
    def save_client():
        try:
            body = SaveClientRequest.model_validate(request.get_json(force=True) or {})
        except ValidationError as e:
            return jsonify(validation_error_response(e)), 400

        report = ClientReport(
            user_id=current_user.id,
            company_name=body.company_name,
            form_json=json.dumps(body.form),
            scorecard_json=json.dumps(body.scorecard),
            insights_json=json.dumps(body.insights) if body.insights else None,
        )
        db.session.add(report)
        db.session.commit()
        logger.info("Client report saved.", extra={"user_id": current_user.id, "report_id": report.id})
        return jsonify({"id": report.id}), 201

    @app.route("/api/clients/<int:client_id>", methods=["GET"])
    @login_required
    def get_client(client_id):
        report = ClientReport.query.filter_by(id=client_id, user_id=current_user.id).first()
        if not report:
            return jsonify({"error": "Not found."}), 404
        return jsonify({
            "id": report.id,
            "company_name": report.company_name,
            "saved_at": report.saved_at.isoformat(),
            "form": json.loads(report.form_json),
            "scorecard": json.loads(report.scorecard_json),
            "insights": json.loads(report.insights_json) if report.insights_json else None,
        })

    @app.route("/api/clients/<int:client_id>", methods=["DELETE"])
    @login_required
    def delete_client(client_id):
        report = ClientReport.query.filter_by(id=client_id, user_id=current_user.id).first()
        if not report:
            return jsonify({"error": "Not found."}), 404
        db.session.delete(report)
        db.session.commit()
        logger.info("Client report deleted.", extra={"user_id": current_user.id, "report_id": client_id})
        return "", 204

    # -----------------------------------------------------------------
    # Health check — for uptime monitoring
    # -----------------------------------------------------------------

    @app.route("/healthz")
    def healthz():
        try:
            db.session.execute(db.text("SELECT 1"))
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"status": "error", "detail": str(e)}), 503

    return app


# Module-level app for `flask run`, gunicorn (`app:app`), and Flask-Migrate's
# `flask db` commands, all of which expect to find an app instance here.
app = create_app()


if __name__ == "__main__":
    is_debug = os.environ.get("FLASK_DEBUG") == "1"
    if not os.environ.get("DATABASE_URL"):
        # SQLite local dev convenience only — production uses `flask db
        # upgrade` (Alembic migrations) instead of create_all(), since
        # create_all() only creates missing tables and silently does
        # nothing when you change an existing model. See README.
        with app.app_context():
            db.create_all()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=is_debug)
