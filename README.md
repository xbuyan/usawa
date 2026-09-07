# Usawa — Equity Scorecard

A DEI equity audit tool: upload employee and applicant data, get a scored
breakdown of pay, promotion, hiring, and representation gaps — scored against
the EEOC's four-fifths rule where a real legal standard applies — plus
AI-generated recommendations. Accounts are authenticated, and every saved
report is scoped to the user who created it.

## What's in this project

```
equity-scorecard-app/
├── app.py                 # Flask backend — all routes, auth wiring
├── auth.py                 # Registration, login, logout
├── models.py                # SQLAlchemy models (User, ClientReport)
├── dei_scorecard.py          # Scoring formulas (four-fifths rule, pay gap, etc.)
├── csv_aggregation.py         # Turns raw employee/applicant CSVs into scores
├── ai_insights.py              # Calls the Claude API for recommendations
├── requirements.txt
├── templates/
│   ├── index.html               # Main app page (requires login)
│   ├── login.html                # Login page
│   └── register.html              # Registration page
├── static/
│   ├── style.css
│   └── app.js                      # Frontend logic (vanilla JS, no build step)
├── render.yaml               # Render Blueprint — deploys web service + Postgres as one unit
├── Procfile                   # Start command for platforms using the Heroku-style convention (Railway, etc.)
└── usawa.db                         # Created automatically on first run (SQLite, local dev only)
```

## Run it locally

1. Install dependencies:
   ```
   pip install -r requirements.txt --break-system-packages
   ```
   (Drop `--break-system-packages` if you're using a virtual environment instead.)

2. Set required environment variables:
   ```
   export ANTHROPIC_API_KEY=your_key_here
   export SECRET_KEY=any-random-string-for-local-dev
   ```
   `SECRET_KEY` signs your session cookies — for local dev any random string
   works, but generate a real one before deploying (see below).

3. Run the app:
   ```
   python3 app.py
   ```

4. Open http://localhost:5000 — you'll be redirected to `/register` to create
   your first account, since every route now requires login.

Locally, `usawa.db` (SQLite) is created automatically — no setup needed. This
only applies to local development; production uses Postgres (see below).

## Deploying it for real

### Required environment variables in production

| Variable | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | From console.anthropic.com |
| `SECRET_KEY` | Yes | The app refuses to start without one outside debug mode. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` and keep it out of source control. |
| `DATABASE_URL` | Yes | A Postgres connection string, e.g. `postgresql://user:pass@host:5432/dbname`. Without this, the app falls back to a local SQLite file, which most hosts reset on every deploy — fine for testing, not for real client data. |
| `PORT` | No | Defaults to 5000 |
| `FLASK_DEBUG` | No | Leave unset (or `0`) in production. Never set to `1` outside local dev — debug mode exposes a lot more than it should if it's ever reachable publicly. |

### Render.com — using render.yaml (recommended, fastest path)

This repo includes `render.yaml`, which defines the whole deployment —
web service, Postgres database, and environment variables — as code. Render
reads it automatically via "Blueprints."

1. Push this repo to GitHub (see `.gitignore` — make sure `usawa.db`, `.env`,
   and any real secrets never get committed).
2. Go to render.com → **New** → **Blueprint** → connect your repo.
3. Render detects `render.yaml` and shows you the plan: one Postgres database
   (`usawa-db`) and one web service (`usawa`), already wired together —
   `DATABASE_URL` is set automatically from the database, and `SECRET_KEY` is
   auto-generated securely by Render itself.
4. You'll be prompted to enter the one value marked `sync: false` in the
   blueprint: `ANTHROPIC_API_KEY`. Paste your key.
5. Click **Apply**. Render provisions both resources and deploys.

This is the reproducible path — if you ever need a staging environment or
have to rebuild this from scratch, it's one blueprint apply instead of
re-clicking through dashboard settings from memory.

### Render.com — manual dashboard setup (alternative)

If you'd rather not use the blueprint, or already have infrastructure:

1. Push this folder to a GitHub repository — **make sure `.gitignore`
   excludes `usawa.db`, `.env`, and anything with real secrets in it.**
2. Create a **Postgres** instance on Render (free tier available) — copy its
   connection string.
3. Create a **Web Service**, connect your repo:
   - **Build command:** `pip install -r requirements.txt && FLASK_APP=app.py flask db upgrade`
   - **Start command:** `gunicorn app:app` (also defined in `Procfile`)
4. Under Environment Variables, add `ANTHROPIC_API_KEY`, `SECRET_KEY`, and
   `DATABASE_URL` (the Postgres connection string from step 2). Generate a
   real `SECRET_KEY` yourself first:
   ```
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
5. Deploy.

**This build command matters — don't drop the `flask db upgrade` part.**
Tables are NOT created automatically on Postgres. `db.create_all()` only
runs for local SQLite dev convenience (see the `if __name__ == "__main__"`
block in `app.py`) — gunicorn never executes that code path in production.
Skipping the migration step means every table-dependent request (including
registration) fails with `relation "users" does not exist` until you run
`flask db upgrade` against the production database at least once. Baking
it into the build command means it runs automatically on every deploy,
including the very first one.

### Railway.app

`Procfile` is included, which Railway recognizes automatically. Connect the
repo, attach a Postgres plugin, set the same three environment variables
(`ANTHROPIC_API_KEY`, `SECRET_KEY`, `DATABASE_URL` — Railway usually injects
`DATABASE_URL` automatically once Postgres is attached, check its dashboard).

## Security decisions already built in

Since you asked for security as a foundation, here's what's already handled
and why, so you can speak to it directly. Every claim below was actually
tested, not just written — see `tests/` for the automated suite.

- **Passwords** are never stored in plain text — only a salted scrypt hash
  (Werkzeug's `generate_password_hash`), which is slow-by-design and resistant
  to brute-force/rainbow-table attacks, unlike a fast hash like plain SHA256.
- **Login errors are deliberately vague** ("Invalid email or password" for
  both a wrong email and a wrong password) — tested directly that both cases
  produce an identical error message, preventing account enumeration.
- **Every saved report is scoped to `user_id`** at the database query level —
  tested directly: a second user's client list comes back empty, and
  fetching or deleting another user's report by ID returns 404, not their data.
- **CSRF protection** (Flask-WTF) — every state-changing request needs a
  valid token, sent via the `X-CSRFToken` header from the frontend. Tested
  directly: a request without the token is rejected (400), the same request
  with it succeeds (201).
- **Rate limiting** (Flask-Limiter) — login, registration, CSV uploads, and
  the AI insights endpoint (which costs real money per call) are capped.
  **Known limitation:** the default in-memory storage only enforces limits
  correctly with a single process — running multiple gunicorn workers means
  each worker counts separately, so the effective limit becomes
  (stated limit × worker count). Move to Redis-backed storage before scaling
  past one worker.
- **Security headers** (Flask-Talisman) — Content-Security-Policy,
  X-Frame-Options, X-Content-Type-Options, and Strict-Transport-Security are
  set on every response. Verified directly in response headers.
  **Known trade-off:** the CSP allows `unsafe-inline` for styles only (not
  scripts), because templates use inline `style=""` attributes throughout.
  Removing this means refactoring every inline style to a CSS class first —
  a real task, not done yet. Script sources are strict (`'self'` plus the
  one CDN used for CSV parsing) with no exceptions.
- **File upload limits** — a hard 5MB cap on total request size
  (`MAX_CONTENT_LENGTH`) and a 20,000-row cap on CSV parsing, both tested
  directly: an oversized request returns a clean 413, an oversized CSV
  returns a clean 400 with an actionable message, neither crashes the server.
- **Session cookies are httpOnly** (JavaScript can't read them, blocking a
  common XSS cookie-theft path), **SameSite=Lax** (blocks basic CSRF), and
  **Secure** (HTTPS-only) once not running in debug mode.
- **SQL injection is structurally prevented** — SQLAlchemy's ORM parameterizes
  every query; the app never builds SQL from string concatenation.
- **Every API error returns JSON**, even unhandled crashes, CSRF failures,
  oversized uploads, and unauthorized access — all route through one error
  handler, tested directly so the frontend never breaks on an HTML error
  page instead of a real message.
- **`SECRET_KEY` is mandatory in production** — the app raises an error and
  refuses to start rather than silently falling back to an insecure default,
  which is a common real-world vulnerability in Flask apps.
- **Schema migrations are managed with Alembic** (via Flask-Migrate), not
  `db.create_all()`. A real migration is already generated and tested
  (`migrations/versions/`) — applying it creates the exact expected tables.
  Future schema changes go through `flask db migrate` / `flask db upgrade`,
  which can alter existing tables safely; `db.create_all()` cannot.
- **Automated test suite** (`tests/`, pytest) — 29 tests covering auth, data
  isolation, the scoring engine (including exact four-fifths-rule boundary
  cases), and CSV parsing edge cases. Run with `pytest tests/ -v`. This is
  what catches a regression before it reaches a real client, instead of
  relying on manual spot-checks.
- **Health check endpoint** (`/healthz`) — checks the database is actually
  reachable, not just that the process is running. Point your uptime monitor
  at this.

## Running the test suite

```
pip install -r requirements.txt --break-system-packages
pytest tests/ -v
```

Tests run against an isolated in-memory SQLite database — they never touch
your real `usawa.db` or a production database, and don't require
`ANTHROPIC_API_KEY` to be set (AI insights calls aren't covered by automated
tests yet, since that needs either a real API key or a mocked client).

## Managing schema changes

```
export FLASK_APP=app.py
flask db migrate -m "describe your change"   # generates a new migration file
flask db upgrade                              # applies it
```

Always review the auto-generated migration file before applying it —
Alembic's autogenerate is good but not perfect, especially for column type
changes or renames (it may see a rename as "drop one column, add another,"
losing data — check this manually when it applies).

## What's still missing before this is a fully mature production system

Being direct, so nothing here is a surprise later — this is what remains
after Tier 1 hardening (rate limiting, CSRF, security headers, file upload
limits, migrations, and automated tests, all covered above):

- **No password reset flow** — if a user forgets their password today, there's
  no "forgot password" email flow yet. Needed before real users onboard
  themselves.
- **No email verification** — anyone can register with any email address
  without proving they own it.
- **No audit log** — for a tool handling sensitive pay/demographic data, a
  log of who viewed/exported what, and when, is standard practice and worth
  adding before enterprise clients ask for it.
- **No account lockout after repeated failed logins** — rate limiting slows
  brute-force attempts but doesn't lock an account after N failures.
- **No structured/JSON logging** — current logs are plain print statements,
  which gets hard to search once there's real production traffic.
- **No error monitoring service** (e.g. Sentry) — a crash currently only
  shows up in server logs; nothing alerts you when it happens.
- **No dependency vulnerability scanning** — nothing currently checks
  `requirements.txt` against known CVEs (pip-audit or GitHub Dependabot
  would close this).
- **No industry benchmarks yet** — comparing a company's scores to aggregate
  data across your client base isn't wired in yet; needs 10+ real clients'
  worth of data first.
- **CSV column names must match the template exactly** — a flexible column
  mapper is still a good next improvement.
- **Regression-based pay equity** (controlling for tenure, performance,
  location — what Trusaic's engine actually does) is a meaningfully bigger
  statistical undertaking than the level-based comparison this tool currently
  does. Worth scoping as its own project phase.
- **Gunicorn defaults are untuned** — no explicit worker count or timeout
  configuration for real concurrent load.

## Updating the scoring logic

All the scoring math lives in `dei_scorecard.py`, isolated from the web layer
and from auth. To change a threshold or weight, edit that file only.

## Scoring methodology (read this before pitching to HR/Legal)

Two different kinds of claims are mixed into one 0-100 score, and it matters
which is which when you're presenting this to someone who will push back:

**Hiring funnel and promotion equity** are scored against the **EEOC
four-fifths rule** (29 CFR 1607.4(D)) — a real, citable regulatory screening
test used in adverse-impact analysis: a selection rate for any group below
80% of the highest group's rate is generally regarded as evidence of adverse
impact. This is genuinely defensible in front of HR/Legal — it's the same
test the EEOC itself uses as a first-pass screen, not something this tool
invented. The AI-generated recommendations will cite this explicitly when a
metric fails it (e.g. "this hiring stage falls below the four-fifths
threshold").

**Pay equity and representation pipeline** do NOT have an equivalent legal
test. Pay equity thresholds here (5% unexplained gap as a caution point, 15%+
as severe) reflect common practice among pay equity consultancies, not law —
and this tool's pay gap calculation is simplified (grouped by level only,
not controlling for tenure, performance, or role scope the way a real pay
equity audit would). Representation pipeline ("leaky pipeline") drop-off has
no regulatory standard at all — it's a descriptive pattern, useful for
spotting where representation erodes, but should never be presented as a
compliance finding.

**Before you pitch this as a product**, be direct with prospects about this
split: the hiring/promotion numbers can be defended with a citation, the pay
and representation numbers are directional signals that would need a real
audit (ideally with an employment attorney or certified pay equity analyst)
before anyone acts on them in a way that has legal consequences.

