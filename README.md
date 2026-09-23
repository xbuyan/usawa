# Usawa — Equity Scorecard

A DEI equity audit tool: upload employee and applicant data, get a scored
breakdown of pay, promotion, hiring, and representation gaps — scored against
the EEOC's four-fifths rule where a real legal standard applies — plus
AI-generated recommendations grounded in peer data. Accounts are
authenticated, and every saved report is scoped to the user who created it.

Three product layers:

1. **The audit tool** — CSV upload → scorecard (four-fifths rule for
   hiring/promotion, practice-based measures elsewhere) → AI
   recommendations.
2. **The learning layer** — an opt-in, anonymized, k-anonymized benchmark
   network. As more companies participate, Usawa materializes cohort
   percentiles ("your pay equity score is at the 62nd percentile of small
   software companies") and **mines patterns** ("cohorts with weak
   hiring-funnel scores tend to show lower pay equity — correlation 0.6,
   based on 40 companies"). The recommendation engine gets more specific
   with more data, and every number names its cohort and sample size.
3. **The DEI assistant** — a retrieval-grounded chatbot over a curated
   knowledge base ("how do I write an inclusive job posting for a senior
   engineer role?"). Answers cite their sources; when nothing in the KB
   grounds an answer, it says so instead of improvising.

## What's in this project

```
equity-scorecard-app/
├── app.py                 # Flask backend — all routes, auth wiring
├── auth.py                 # Registration, login, logout
├── models.py                # SQLAlchemy models (User, ClientReport, CompanySnapshot,
│                            #   BenchmarkStats, LearnedPattern, Conversation, ChatMessage)
├── dei_scorecard.py          # Scoring formulas (four-fifths rule, pay gap, etc.)
├── csv_aggregation.py         # Turns raw employee/applicant CSVs into scores
├── pay_equity_regression.py    # OLS regression-adjusted pay gap
├── ai_insights.py              # Calls the Claude API for recommendations
├── benchmarks.py               # Learning layer: snapshot capture, cohort percentiles,
│                              #   pattern mining, k-anonymity, debounced recompute
├── chatbot.py                  # Grounded DEI assistant (retrieval + Claude)
├── knowledge_base.py           # TF-IDF retrieval over the KB (pgvector-ready seam)
├── kb_documents.py             # The curated DEI knowledge base (15 documents)
├── seed_demo_data.py           # Deterministic demo companies for the learning layer
│                              #   (first-deploy data; refuses to touch real captures)
├── schemas.py                  # Pydantic request validation
├── requirements.txt
├── templates/
│   ├── index.html               # Main app page (requires login)
│   ├── login.html                # Login page
│   └── register.html              # Registration page
├── static/
│   ├── style.css
│   ├── app.js                      # Frontend logic (vanilla JS, no build step)
│   └── assistant.js                 # Chat UI + benchmarks panel (vanilla JS)
├── render.yaml               # Render Blueprint — deploys web service + Postgres + Redis as one unit
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

   Optional: set `REDIS_URL` (e.g. `redis://localhost:6379/0`) for
   rate-limit storage. Without it, rate limiting falls back to in-memory
   storage — fine for local dev (a single process), but NOT correct in
   production, where the app runs multiple gunicorn workers. See
   `extensions.py` for details.

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
| `SENTRY_DSN` | No | From sentry.io, if you want error monitoring. Does nothing if unset — no behavior change, no crash. |
| `REDIS_URL` | Yes (prod) | Shared storage for rate limiting across gunicorn workers. `render.yaml` provisions it automatically. Loud startup warning if unset in production mode. |
| `ANTHROPIC_MODEL` | No | Overrides the model used by `/api/chat` and `/api/insights` (default: `claude-sonnet-5`). A deploy lever — switch models from the dashboard without a code change. |
| `MAIL_SERVER` | No | SMTP host (e.g. `smtp.sendgrid.net`). Without this, password-reset and verification emails are logged instead of sent — fine for testing, not for real users who need to actually receive the email. |
| `MAIL_PORT` | No | Defaults to 587 (standard SMTP+TLS port) |
| `MAIL_USERNAME` | No | SMTP auth username |
| `MAIL_PASSWORD` | No | SMTP auth password |
| `MAIL_DEFAULT_SENDER` | No | Defaults to `noreply@usawa.co.ke` — set this to an address your SMTP provider is authorized to send from |

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

#### First deploy checklist (new features)

Everything the new features need is already wired in `render.yaml`:

- `REDIS_URL` is injected from the provisioned key-value store — the
  rate limiter is correctly shared across both gunicorn workers from the
  first request.
- `ANTHROPIC_API_KEY` is the one `sync: false` value you paste at deploy
  time. Without it the app still boots — `/api/chat` and `/api/insights`
  return an honest 502 telling you the key is missing — but the AI
  features are dead until you add it (Dashboard → your web service →
  Environment → add `ANTHROPIC_API_KEY` → save, which redeploys).
- `ANTHROPIC_MODEL` (optional, also `sync: false`) overrides the model
  both AI features use, no code change needed.
- Migrations run on every build (`flask db upgrade` in the build
  command), so the learning-layer and chat tables — and the
  `company_snapshots.seeded` flag — exist before the first request.

**Demo data for the benchmarks feature:** a fresh deploy has empty
cohorts, so `/api/benchmarks` honestly says "not enough companies yet"
for everything. To demo the feature with data, run the seeder once from
a shell (`render.com shell` or locally against the production DB):

```
python3 seed_demo_data.py
```

It generates 48 deterministic synthetic companies (4 industries × 2 size
bands × 6), materializes cohort percentiles, and mines realistic
patterns. It refuses to run if any REAL company data exists (demo rows
are flagged `seeded` in the DB and never blend into real cohorts), a
plain re-run refuses instead of silently doubling cohort sizes, and
`--clear` removes only the demo rows. See the header of
`seed_demo_data.py` for the full contract and `--force`/`--status`.

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
- **Rate limiting** (Flask-Limiter), Redis-backed. This closes a gap that
  was live in production, not just theoretical: the app runs 2 gunicorn
  workers (`Procfile`/`render.yaml`), and the original in-memory storage
  gave each worker its own separate counter — the real, effective limit
  was inconsistent depending on which worker handled a given request.
  Fixed via `REDIS_URL` (`render.yaml` now provisions a Redis instance);
  falls back to in-memory with a loud startup warning if `REDIS_URL` isn't
  set, which is fine for local dev (single process) but wrong for
  production. **Tested against a real Redis server**, with a test that
  reproduces the original bug and proves the fix (`test_rate_limiting.py`).
- **Account lockout** — a second, independent layer alongside IP-based rate
  limiting: 5 consecutive failed logins locks the specific account for 15
  minutes, regardless of source IP. Tested directly, including against a
  real Alembic migration applied to a table with a pre-existing row (the
  naive autogenerated version would have broken on any real production
  data — see `migrations/versions/db74a3830402_*.py`).
- **Real client IP resolution** (`werkzeug.middleware.proxy_fix.ProxyFix`,
  trusting exactly one hop). Render terminates TLS at a reverse proxy, so
  without this, `request.remote_addr` — used by both rate limiting and the
  audit log below — would see the proxy's address for every request, not
  the real client's. Tested directly with a simulated `X-Forwarded-For`
  header, confirming the resolved IP matches the forwarded value, not a
  loopback default.
- **Audit log** (`AuditLog` model, `audit_log.py`) — a durable, queryable
  record (not just a log line) of who did what and when: login
  success/failure/lockout, employee/applicant CSV uploads, AI insights
  generation, assistant messages, sharing-preference changes, and
  creating/viewing/deleting a saved client report. Scoped
  to `user_id` the same way client reports are; exposed via
  `GET /api/audit-log` for a user's own history. Deliberately does NOT log
  every read (e.g. the summary client list) to avoid drowning the
  signal — only actions that touch actual sensitive data content.
- **Learning-layer privacy is structural** (`benchmarks.py`, `models.py`) —
  benchmark contribution is opt-in per user (`share_anonymized_data`, off
  by default); snapshots carry no user_id column and no company name
  (capture's signature cannot receive either — tested); company size is
  bucketed into bands so exact headcount can't identify anyone; and no
  cohort statistic or pattern is materialized below MIN_COHORT = 5
  companies (tested at the database level — absence IS the enforcement).
  The benchmarks UI states the selection-bias caveat to users.
- **Assistant anti-hallucination is enforced in code, not vibes** —
  retrieval requires meaningful overlap (≥2 distinct matched terms, or a
  curated-tag match) before any document is trusted as grounding; with no
  match, the model is explicitly instructed to say it lacks vetted
  guidance. Questions are length-capped at the schema, again in the
  chatbot, and history is bounded (6 turns), so prompt cost per request is
  capped. Conversations are ownership-checked like every other resource.
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
- **Automated test suite** (`tests/`, pytest) — 115 tests covering auth,
  account lockout, audit logging, data isolation, exact four-fifths-rule boundary cases,
  CSV parsing edge cases and flexible column mapping, regression-adjusted
  pay equity (verified against synthetic data with a known true answer),
  the learning layer (exact percentile values, k-anonymity at the DB
  level, pattern mining vs a known-answer cohort, suppression of weak
  patterns, snapshot privacy structure, debounce), the assistant
  (retrieval precision, grounded vs ungrounded prompt construction,
  conversation ownership isolation, honest failure modes), migrations
  against tables with pre-existing rows (added after a real
  production migration failure — see PROJECT_STATUS.md), rate limiting
  (against a real Redis server), password reset, email verification, and
  Pydantic validation. Run with `pytest tests/ -v`. This
  is what catches a regression before it reaches a real client, instead of
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
`ANTHROPIC_API_KEY` to be set (the AI-calling code paths are tested with
the Anthropic client mocked at the API boundary; what's proven is our
grounding decisions, prompt construction, persistence, and failure modes —
not the model's prose quality).

## API reference (current surface)

| Method & path | What it does |
|---|---|
| `POST /api/auth/register` | Create account (rate-limited 10/hr) |
| `POST /api/auth/login` | Log in (15/hr, account lockout after 5 failures) |
| `POST /api/auth/logout` | Log out |
| `GET /api/auth/me` | Session info incl. `share_anonymized_data` |
| `POST /api/auth/forgot-password` / `reset-password` | Password reset flow |
| `POST /api/auth/resend-verification` | Resend verification email (5/hr) |
| `POST /api/parse/employee` | Upload employee CSV → aggregated metrics (30/hr) |
| `POST /api/parse/applicant` | Upload applicant CSV → funnel counts (30/hr) |
| `POST /api/score` | Run the scorecard on submitted data |
| `POST /api/insights` | AI recommendations, enriched with learned peer patterns (30/hr) |
| `GET/POST /api/clients` | List / save client reports (owned by current user) |
| `GET/DELETE /api/clients/<id>` | Fetch / delete one report (owner only) |
| `POST /api/chat` | Ask the grounded DEI assistant (20/hr) |
| `GET /api/conversations` | List the user's conversations |
| `GET/DELETE /api/conversations/<id>` | Fetch / delete one conversation (owner only) |
| `GET /api/benchmarks` | Compare a scorecard to anonymized peer cohorts |
| `POST /api/sharing` | Opt in/out of anonymous benchmark contribution |
| `GET /api/audit-log` | The user's own audit history (200 most recent) |
| `GET /healthz` | Uptime check incl. real DB round-trip |

All mutating endpoints require the `X-CSRFToken` header; all user-owned
resources are query-scoped to `current_user.id`.

## How the learning layer works (and its guarantees)

1. **Opt-in capture.** A user toggles "Contribute anonymized scorecards to
   peer benchmarks." From then on, saving a report writes one
   `CompanySnapshot`: industry (normalized), size **band** (micro ≤50 /
   small / medium / large), the five sub-scores, overall score, and
   aggregate metrics as JSON. No user id. No company name. The capture
   function's signature makes storing either impossible.
2. **Materialization.** Cohort percentiles (10/25/50/75/90 per metric) are
   precomputed into `benchmark_stats`, one row per cohort × metric ×
   point. Serving a comparison is an indexed point lookup — the read path
   is O(1) regardless of how many million snapshots exist. Recompute runs
   at most once per 60s per process (debounced); past single-process
   scale, recompute moves to a background queue (Redis is already in the
   stack) without changing the pure compute functions.
3. **K-anonymity.** A cohort with fewer than 5 companies for a metric
   materializes NOTHING — the row's absence is the enforcement, verified
   by tests at the database level. The UI also never shows a statistic
   without its cohort label and n.
4. **Pattern mining.** Within each cohort, condition metrics
   (hiring_funnel, job_language, representation_pipeline) are tested
   against outcomes (pay_equity, promotion_equity, overall) via Spearman
   rank correlation, split at the condition median. Patterns below |r| =
   0.35, or with fewer than 3 companies on either side, are discarded.
   Surviving patterns carry their correlation and sample size everywhere
   they're shown — including inside AI-generated insights, where the
   system prompt forbids presenting them as causation or legal findings.
5. **Serving.** `GET /api/benchmarks` walks the cohort fallback chain —
   (your industry, your band) → (all industries, your band) → (any band) —
   and states which cohort produced each number.

**Selection-bias caveat, shown to users in-product:** companies that run
equity audits aren't a random sample of companies; benchmarks compare you
to similar *engaged* employers, not the market average.

## How the DEI assistant is grounded

- **Curated corpus** (`kb_documents.py`): 15 vetted documents covering
  inclusive postings (with a worked senior-engineer example), the
  four-fifths rule, structured interviews, pay-equity methodology,
  promotion calibration, pipeline reading, Kenya-specific law and context,
  benchmark interpretation, sourcing, retention, program setup,
  accessibility, ERGs, and CSV data handling. Grows from real usage —
  assistant answers with no retrieved sources are logged (NULL
  `sources_json`) and mined to decide what to write next.
- **Retrieval** (`knowledge_base.py`): TF-IDF with curated synonym tags,
  plus a match-qualification rule (≥2 distinct matched terms, or a tag
  match) so one incidental word can't produce false grounding. The
  function signature is the seam for pgvector embeddings when the corpus
  outgrows keyword-scale.
- **Generation** (`chatbot.py`): Claude receives the retrieved documents
  verbatim, a compact view of the user's current scorecard, and strict
  rules: cite what you use as `[source: doc_id]`, never invent statistics
  or legal citations, treat the four-fifths rule as a screening standard
  (not a statute), and when nothing matches, say so. Sources are returned
  structured and rendered as chips in the UI. Every message is stored on
  the user's own conversation and audited.

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

## Tier 2 additions (password reset, verification, monitoring, validation)

Building on Tier 1, all tested before shipping:

- **Password reset** — stateless, signed, expiring tokens (itsdangerous, no
  extra database table). A token embeds a fingerprint of the *current*
  password hash, so once a password is actually reset, the fingerprint
  changes and the same token can't be replayed — tested directly: reusing
  a token after the password changes is rejected with a clear message.
  Tokens expire after 1 hour. Rate limited (10/hour on reset, 5/hour on the
  request-a-link step, since that step triggers an email send).
- **Email verification** — same stateless-token approach, 3-day expiry.
  **Deliberately non-blocking**: an unverified user can still log in and use
  the tool — they see a dismissible-feeling banner with a "resend" button
  instead of being locked out. This was a judgment call, not an oversight:
  hard-blocking unverified users is more secure but risks locking out a real
  user during a live pitch demo if email delivery has any hiccup. Revisit
  this trade-off once you're onboarding real clients rather than demoing.
- **Real email sending** (Flask-Mail, standard SMTP — works with Gmail SMTP,
  SendGrid, Mailgun, Postmark, etc.) — **with an honest limitation: this has
  NOT been tested against a real SMTP server or a real inbox**, since that
  needs real credentials this environment doesn't have. If `MAIL_SERVER`
  isn't set, the app logs the email content instead of sending it (visible
  directly in the structured logs) — this is what let the reset/verification
  flows be tested end-to-end without real credentials. Set `MAIL_SERVER`,
  `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER` to
  enable real delivery, then **test it yourself with a real inbox** before
  trusting it — deliverability depends on your provider's sender reputation
  and SPF/DKIM setup, which no amount of correct code can guarantee.
- **Error monitoring (Sentry)** — activates automatically if `SENTRY_DSN` is
  set; does nothing (no crash, no behavior change) if it's left unset. Wired
  into the same error handler that already guarantees JSON responses, so a
  production crash now reaches you instead of only living in server logs
  nobody's watching.
- **Structured (JSON) logging** — every log line is now a JSON object with a
  timestamp, level, and message, verified directly in the output. In local
  dev (`FLASK_DEBUG=1`) logs stay human-readable instead, since nobody wants
  to read raw JSON while developing.
- **Input validation (Pydantic)** — `/api/score`, `/api/insights`,
  `/api/clients`, and all `/api/auth/*` routes now validate the request body
  against an explicit schema before any business logic runs. A malformed
  request gets a clean 400 with the specific field and reason, tested
  directly (e.g. a negative promotion count is rejected with
  `"promotion.promotions_a: Input should be greater than or equal to 0"`)
  instead of either crashing or silently doing the wrong thing with a
  missing field defaulting to `None`.
- **Gunicorn worker tuning** — `--workers 2 --worker-class gthread --threads 4
  --timeout 120`. Reasoning: Render's free tier gives 0.1 CPU/512MB, so
  worker count stays low; threads (not more processes) handle concurrent
  requests without multiplying memory use; the 120s timeout accounts for
  the AI insights call, which can take a while waiting on the Claude API —
  the previous unconfigured default would have killed slow requests
  prematurely under real load. Revisit these numbers if you upgrade off the
  free tier.

## What's still missing before this is a fully mature production system

Being direct, so nothing here is a surprise later — this is what remains
after Tier 1, Tier 2, and the September 2026 hardening passes (Redis rate
limiting, account lockout, flexible CSV column mapping, dependency
scanning + CI, an audit log with real client-IP resolution, and
regression-adjusted pay equity), all covered above:

- **Email deliverability is untested** — see the honest caveat above. Real
  SMTP credentials and a real test send are needed before relying on this.
- **No industry benchmarks yet** — comparing a company's scores to aggregate
  data across your client base isn't wired in yet; needs 10+ real clients'
  worth of data first.
- **Regression-adjusted pay equity is not wired into the frontend UI yet**
  — the API computes and returns it, but nothing in `static/app.js`
  displays it. The backend piece is done and tested; the UI piece isn't.
- **Regression-adjusted pay equity controls for level, tenure, and
  performance — not "role scope"** in any finer sense (team size, budget,
  scope of responsibility). Reducing that to a clean column needs a
  customer-specific job architecture, which is out of scope for now. Real
  remaining gap versus Trusaic's actual engine, just narrower than before.
- **Regression-adjusted pay equity has not been validated against a real,
  messy customer dataset** — verified against synthetic data with a known
  true answer (see `tests/test_pay_equity_regression.py`), which proves the
  math is implemented correctly, but real HR data (missing values, outliers,
  small subgroups) will exercise the guard rails (sample-size floors,
  collinearity detection) in ways synthetic data can't fully anticipate.
- **CI has not been observed running on a real push yet** — the GitHub
  Actions workflow (`.github/workflows/ci.yml`) was written and every
  command in it was verified locally in a sandbox (real pytest run against
  real Redis, real pip-audit run), but nobody has watched it go green in
  GitHub's own environment yet. Push to `main` (or open a PR) and check
  the Actions tab before trusting it fully — this project has already
  learned once, the hard way (see Tier 1's migration incident), that
  "works locally" and "works in the real target environment" are
  genuinely different tests.
- **Render's Auto-Deploy was broken for several pushes (Sept 10–18, 2026)
  — root cause found and fixed, confirmed working.** Every push in that
  window required a manual "Deploy latest commit" click; Render's
  Deploys tab never picked up new commits on its own. Root cause:
  Render's GitHub connection had lost visibility into this specific repo
  (`xbuyan/usawa` no longer appeared when searching for it in Render's
  "Update Source" dialog), even though Build & Deploy settings
  themselves looked correct (right repo shown, right branch, Auto-Deploy
  set to "On Commit"). Fixed by re-selecting the repo through Render's
  Update Source flow. **One real gotcha hit during the fix**: that flow
  resets Build/Start Command fields to generic defaults — it silently
  offered `gunicorn app:app` in place of the actual tuned command
  (`--workers 2 --worker-class gthread --threads 4 --timeout 120
  --graceful-timeout 30 --access-logfile - --error-logfile -`). Caught
  and corrected before deploying, by diffing against `render.yaml`
  rather than accepting the modal's pre-filled value — losing
  `--timeout 120` specifically would have risked the AI insights call
  getting killed mid-request under gunicorn's 30s default timeout.
  **Confirmed fixed**: the commit that added this note reached Render
  and deployed with no manual trigger — verified directly in Render's
  Deploys tab, not assumed. If a future push ever needs a manual deploy
  again, treat that as a regression worth re-diagnosing, not "back to
  normal" — this was a real, once-broken thing, not an inherent quirk of
  the platform.

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

**Pay equity** has two versions now, both surfaced, clearly labeled, side by
side — never one quietly standing in for the other:

- **Level-based gap** (`pay_gap_by_level`, always computed): average pay
  compared within the same job level only. Thresholds (5% as a caution
  point, 15%+ as severe) reflect common pay-equity-consultancy practice, not
  law.
- **Regression-adjusted gap** (`regression_adjusted_pay_equity`, computed
  whenever the upload includes tenure and performance rating — both
  optional columns): an OLS regression of salary on level, tenure, and
  performance rating, plus a group indicator. The coefficient on the group
  indicator is the pay difference that survives controlling for those
  legitimate factors — much closer to what a real pay equity audit (and
  Trusaic's actual engine) reports, versus a raw level-grouped average that
  might just reflect one group having more tenure or higher ratings.
  Includes a p-value and a `statistically_significant` flag (p < 0.05);
  below at least 30 usable rows (and 5+ per group), it reports
  `usable: false` with a specific reason instead of guessing — see
  `pay_equity_regression.py` for the exact guards (sample size, group
  balance, collinearity, singular-matrix protection).
  **Honest scope limit:** this controls for level, tenure, and performance
  — NOT "role scope" in any finer-grained sense (team size, budget,
  scope of responsibility), since there's no clean way to reduce that to a
  column without a customer-specific job architecture. That's still a real
  gap versus Trusaic's actual engine, just a smaller one than before.
  **Not yet wired into the frontend UI** — the number is computed and
  returned by the API (`/api/parse/employee`, `/api/score`), but nothing
  in `static/app.js` displays it yet. Tracked here explicitly rather than
  silently left out of both the code and the "what's missing" list.

Representation pipeline (\"leaky pipeline\") drop-off has
no regulatory standard at all — it's a descriptive pattern, useful for
spotting where representation erodes, but should never be presented as a
compliance finding.

The same honesty standard applies to the **learning layer and the
assistant**: benchmark numbers always name their cohort and sample size;
mined patterns are labeled as correlations with their n, never causation;
and assistant answers cite their sources or say plainly that no vetted
guidance matched. None of these outputs are legal findings.

**Before you pitch this as a product**, be direct with prospects about this
split: the hiring/promotion numbers can be defended with a citation, the
regression-adjusted pay number is a real statistical control (when there's
enough data for it to run) but still not a legal finding, and the
representation numbers are directional signals — all of it would need a
real audit (ideally with an employment attorney or certified pay equity
analyst) before anyone acts on it in a way that has legal consequences.

