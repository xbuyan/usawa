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
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app` (also defined in `Procfile`)
4. Under Environment Variables, add `ANTHROPIC_API_KEY`, `SECRET_KEY`, and
   `DATABASE_URL` (the Postgres connection string from step 2). Generate a
   real `SECRET_KEY` yourself first:
   ```
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
5. Deploy. The app will create its tables automatically on first request via
   `db.create_all()` — for a real production app with schema changes over
   time, migrate to Flask-Migrate/Alembic instead of relying on this (see
   "What's still missing" below).

### Railway.app

`Procfile` is included, which Railway recognizes automatically. Connect the
repo, attach a Postgres plugin, set the same three environment variables
(`ANTHROPIC_API_KEY`, `SECRET_KEY`, `DATABASE_URL` — Railway usually injects
`DATABASE_URL` automatically once Postgres is attached, check its dashboard).

## Security decisions already built in

Since you asked for security as a foundation, here's what's already handled
and why, so you can speak to it directly:

- **Passwords** are never stored in plain text — only a salted scrypt hash
  (Werkzeug's `generate_password_hash`), which is slow-by-design and resistant
  to brute-force/rainbow-table attacks, unlike a fast hash like plain SHA256.
- **Login errors are deliberately vague** ("Invalid email or password" for
  both a wrong email and a wrong password) — this prevents an attacker from
  using the login form to enumerate which emails have accounts.
- **Every saved report is scoped to `user_id`** at the database query level —
  one user can never list, view, or delete another user's data, even by
  guessing report IDs (tested directly: user B gets an empty list, not an
  error revealing user A's data exists).
- **Session cookies are httpOnly** (JavaScript can't read them, blocking a
  common XSS cookie-theft path), **SameSite=Lax** (blocks basic CSRF), and
  **Secure** (HTTPS-only) once not running in debug mode.
- **SQL injection is structurally prevented** — SQLAlchemy's ORM parameterizes
  every query; the app never builds SQL from string concatenation.
- **Every API error returns JSON**, even unhandled crashes and unauthorized
  access — verified directly so the frontend never breaks on an HTML error
  page instead of a real message.
- **`SECRET_KEY` is mandatory in production** — the app raises an error and
  refuses to start rather than silently falling back to an insecure default,
  which is a common real-world vulnerability in Flask apps.

## What's still missing before this is a fully mature production system

Being direct, so nothing here is a surprise later:

- **No password reset flow** — if a user forgets their password today, there's
  no "forgot password" email flow yet. Needed before real users onboard
  themselves.
- **No rate limiting on login/register** — someone could currently attempt
  many password guesses in a row. Add Flask-Limiter before this is public.
- **No email verification** — anyone can register with any email address
  without proving they own it.
- **Schema migrations aren't managed** — `db.create_all()` only creates
  tables that don't exist yet; it won't alter existing tables if you change a
  model later. Move to Flask-Migrate (Alembic) before your schema needs to
  evolve on a live database with real data in it.
- **No audit log** — for a tool handling sensitive pay/demographic data, a
  log of who viewed/exported what, and when, is standard practice and worth
  adding before enterprise clients ask for it.
- **No industry benchmarks yet** — comparing a company's scores to aggregate
  data across your client base isn't wired in yet; needs 10+ real clients'
  worth of data first.
- **CSV column names must match the template exactly** — a flexible column
  mapper is still a good next improvement.
- **Regression-based pay equity** (controlling for tenure, performance,
  location — what Trusaic's engine actually does) is a meaningfully bigger
  statistical undertaking than the level-based comparison this tool currently
  does. Worth scoping as its own project phase.

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

