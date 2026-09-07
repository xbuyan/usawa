"""
Usawa (equity scorecard) — Flask backend

Routes:
  GET  /                        -> serves the frontend (requires login)
  GET  /login, /register        -> auth pages
  POST /api/auth/register       -> create account
  POST /api/auth/login          -> log in
  POST /api/auth/logout         -> log out
  GET  /api/auth/me             -> current session info
  POST /api/parse/employee      -> upload employee CSV, returns aggregated metrics
  POST /api/parse/applicant     -> upload applicant CSV, returns aggregated metrics
  POST /api/score               -> run calculate_scorecard() on submitted data
  POST /api/insights            -> generate AI insights for a scorecard
  GET  /api/clients             -> list the current user's saved client reports
  POST /api/clients             -> save a client report (owned by current user)
  GET  /api/clients/<id>        -> fetch one saved report (must be owner)
  DELETE /api/clients/<id>      -> delete a saved report (must be owner)

Run locally (SQLite, zero setup):
  pip install -r requirements.txt
  export ANTHROPIC_API_KEY=your_key_here
  export SECRET_KEY=any-random-string-for-local-dev
  python app.py
  # then open http://localhost:5000

Run in production (Postgres):
  Set DATABASE_URL to a postgres:// connection string and SECRET_KEY to a
  real random secret. Same code, no changes needed — see README.md.
"""

import os
import csv
import io
import json

from flask import Flask, request, jsonify, render_template
from flask_login import LoginManager, login_required, current_user

from models import db, User, ClientReport
from dei_scorecard import calculate_scorecard
from csv_aggregation import aggregate_employee_rows, aggregate_applicant_rows
from ai_insights import generate_insights, InsightsGenerationError
from auth import auth_bp

app = Flask(__name__)

# --- Configuration -----------------------------------------------------
# SECRET_KEY signs session cookies — without a real secret, anyone could
# forge a session. Fails loudly in production instead of silently using an
# insecure default, since a weak secret defeats the point of authentication.
secret_key = os.environ.get("SECRET_KEY")
is_debug = os.environ.get("FLASK_DEBUG") == "1"
if not secret_key:
    if is_debug:
        secret_key = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. Generate one with "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
            "and set it before running in production."
        )
app.config["SECRET_KEY"] = secret_key

# DATABASE_URL: Postgres in production, SQLite file locally if unset.
database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    # SQLAlchemy 1.4+/2.x requires the "postgresql://" scheme
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url or (
    "sqlite:///" + os.path.join(os.path.dirname(__file__), "usawa.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Cookie hardening — only send session cookies over HTTPS once we're not in
# local debug mode, and never expose them to JavaScript (mitigates XSS
# cookie theft) or cross-site requests (mitigates CSRF on the cookie itself).
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = not is_debug

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login_page"


@login_manager.unauthorized_handler
def unauthorized():
    # API calls need a clean JSON 401, not a redirect — fetch() follows
    # redirects automatically, which would hand the frontend an HTML login
    # page instead of JSON and reproduce the exact "Unexpected token '<'"
    # crash from before. Page routes still redirect normally.
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not logged in."}), 401
    from flask import redirect, url_for
    return redirect(url_for("auth.login_page"))


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


app.register_blueprint(auth_bp)


@app.errorhandler(Exception)
def handle_any_error(e):
    """
    Ensures every error response is JSON, never Flask's default HTML error
    page — otherwise the frontend's response.json() call fails with a
    confusing "Unexpected token '<'" error instead of a real message.
    """
    import traceback
    from werkzeug.exceptions import HTTPException

    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code

    traceback.print_exc()  # still visible in the server log for debugging
    message = str(e) or "An unexpected server error occurred."
    return jsonify({"error": message}), 500


def read_csv_upload(file_storage):
    """Reads an uploaded CSV file into a list of dicts."""
    text = file_storage.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/app")
@login_required
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# CSV parsing endpoints
# ---------------------------------------------------------------------------

@app.route("/api/parse/employee", methods=["POST"])
@login_required
def parse_employee_csv():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    rows = read_csv_upload(request.files["file"])
    if not rows:
        return jsonify({"error": "The CSV appears to be empty."}), 400
    result = aggregate_employee_rows(rows)
    return jsonify(result)


@app.route("/api/parse/applicant", methods=["POST"])
@login_required
def parse_applicant_csv():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    rows = read_csv_upload(request.files["file"])
    if not rows:
        return jsonify({"error": "The CSV appears to be empty."}), 400
    result = aggregate_applicant_rows(rows)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Scoring + insights
# ---------------------------------------------------------------------------

@app.route("/api/score", methods=["POST"])
@login_required
def score():
    company_data = request.get_json(force=True)
    if not company_data:
        return jsonify({"error": "No data submitted."}), 400
    result = calculate_scorecard(company_data)
    return jsonify(result)


@app.route("/api/insights", methods=["POST"])
@login_required
def insights():
    body = request.get_json(force=True)
    scorecard = body.get("scorecard")
    if not scorecard:
        return jsonify({"error": "Missing scorecard data."}), 400

    try:
        result = generate_insights(
            scorecard,
            company_size=body.get("company_size"),
            industry=body.get("industry"),
            benchmarks=body.get("benchmarks"),
        )
        return jsonify(result)
    except InsightsGenerationError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        # Catches anything the AI SDK might raise that we didn't anticipate
        # (auth errors, connection errors, SDK version mismatches, etc.)
        # so the frontend always gets JSON back, never a raw crash page.
        return jsonify({"error": f"AI insights failed: {e}"}), 502


# ---------------------------------------------------------------------------
# Saved clients — every query is scoped to current_user, so one user can
# never see, load, or delete another user's saved reports.
# ---------------------------------------------------------------------------

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
    body = request.get_json(force=True)
    company_name = body.get("company_name") or "Untitled"
    form_data = body.get("form", {})
    scorecard = body.get("scorecard", {})
    insights_data = body.get("insights")

    report = ClientReport(
        user_id=current_user.id,
        company_name=company_name,
        form_json=json.dumps(form_data),
        scorecard_json=json.dumps(scorecard),
        insights_json=json.dumps(insights_data) if insights_data else None,
    )
    db.session.add(report)
    db.session.commit()
    return jsonify({"id": report.id}), 201


@app.route("/api/clients/<int:client_id>", methods=["GET"])
@login_required
def get_client(client_id):
    report = ClientReport.query.filter_by(id=client_id, user_id=current_user.id).first()
    if not report:
        # Same 404 whether the report doesn't exist or belongs to someone
        # else — never confirm the existence of another user's data.
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
    return "", 204


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=is_debug)
