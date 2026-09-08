# Usawa — Project Status

**Last updated:** after Tier 2 hardening + pricing section added to landing page.

**Read this file first in any new conversation about this project** — it's
the source of truth for what's done, what's not, and the non-negotiable
principles this project is being built under. Paste this whole file into a
new chat to restore full context.

---

## The non-negotiables (stated explicitly by the founder, more than once)

1. **Security is a foundation, not a feature.** Every build decision gets
   evaluated against this before anything else — not bolted on later, not
   traded off for speed.
2. **Absolute honesty over reassurance.** Every claim about what's "done"
   must be backed by an actual test, not just written code. When something
   is untested, unverified, or a genuine trade-off, say so plainly — don't
   soften it.
3. **This project is being built to completion.** No gaps, no permanent
   compromises. Things not yet done should be tracked explicitly (see
   README's "What's still missing" section), not quietly dropped.
4. **Monetization is the real goal.** This isn't a demo for its own sake —
   the founder needs to charge real Kenyan companies real money for this,
   and needs the product and the business built solidly enough to survive
   that.

---

## What Usawa is

A DEI/pay-equity audit tool built specifically for the Kenyan market.
Companies upload employee and applicant data (CSV); Usawa scores pay,
promotion, hiring-funnel, and representation-pipeline equity, and generates
AI-written findings and recommendations.

**Key differentiator, and the thing that makes it defensible in front of
HR/Legal:** hiring funnel and promotion equity are scored against the
**EEOC's four-fifths rule** (29 CFR 1607.4(D)) — a real regulatory standard,
not an invented 0–100 scale. Pay equity and representation pipeline use
practice-based thresholds and are explicitly labeled as such, not dressed up
as legal findings. This honesty-about-methodology is a deliberate product
principle, not just a disclaimer.

**Market positioning:** the Kenyan-market alternative to global DEI
analytics tools (Trusaic/PayParity, Syndio, Diversio) — none of which have
meaningful Kenya presence. Workpay (Nairobi HR/payroll platform) is the
closest local player but focuses on payroll, not equity auditing.

**Current business development:** actively engaging UN Women Kenya, framed
around their WEPs (Women's Empowerment Principles) accountability push —
160+ Kenyan companies are WEPs-aligned and being asked to report progress
(e.g. via the Transparency and Accountability Survey). Usawa is positioned
as the measurement layer that makes that reporting real. A one-page
leave-behind PDF and an outreach email have already been drafted for this
relationship.

**Pricing (drafted, not yet validated with real customers):** tiered flat
monthly fee by company size band, not per-seat (since this is a periodic
audit tool, not daily-use software):
- Starter (≤50 employees): KES 15,000–25,000/month
- Growth (51–200): KES 35,000–60,000/month
- Scale (201–500): KES 70,000–120,000/month
- Enterprise (500+): custom quote

This is live on the landing page's Pricing section. **Not yet validated**
against real prospects — treat as a starting point for conversations, not
a settled number.

---

## Tech stack

- **Backend:** Flask (application factory pattern in `app.py` — this
  matters, it's what makes automated testing possible)
- **Database:** SQLAlchemy ORM — SQLite for local dev (zero setup),
  Postgres in production (Render). Schema migrations via Alembic
  (Flask-Migrate), NOT `db.create_all()` in production.
- **Auth:** Flask-Login, session-based, scrypt password hashing
- **AI:** Anthropic Claude API for generating findings/recommendations
  (`ai_insights.py`)
- **Frontend:** Vanilla JS (no framework/build step) — `static/app.js` for
  the main tool, separate small JS files for login/register/forgot-password
  pages. Deliberately not React/Babel (that was the earlier in-chat artifact
  prototype; the real deployed app is plain JS for reliability)
- **Deployment:** Render.com, `render.yaml` Blueprint (Postgres + web
  service defined together) — **currently live** at the founder's Render
  URL. GitHub-connected, auto-deploys on push to `main`.

---

## Tier 1 — DONE (security & reliability foundation)

All six items implemented AND tested (not just written):

1. **Rate limiting** (Flask-Limiter) — login, register, CSV uploads, AI
   insights endpoint all capped. **Known limitation:** in-memory storage
   only works correctly with one gunicorn worker — needs Redis before
   scaling past that.
2. **CSRF protection** (Flask-WTF) — every mutating request needs
   `X-CSRFToken` header. Tested: request without token rejected (400),
   same request with token succeeds.
3. **Security headers** (Flask-Talisman) — CSP, X-Frame-Options,
   X-Content-Type-Options, HSTS. **Real bug caught and fixed:**
   `force_https` would have caused a redirect loop on Render (which
   terminates TLS at a proxy) — now `force_https=False` deliberately.
4. **File upload hardening** — 5MB max request size, 20,000-row CSV cap.
   Tested: oversized file → clean 413, oversized CSV → clean 400.
5. **Schema migrations (Alembic/Flask-Migrate)** — real migrations
   generated and tested to apply cleanly. **Production incident that
   happened and was fixed:** the first live deploy hit
   `relation "users" does not exist` because migrations were never run
   against the production Postgres database — gunicorn doesn't execute the
   `if __name__ == "__main__"` block where local dev's `db.create_all()`
   lived. Fixed by making the Render build command run
   `flask db upgrade` automatically on every deploy (in both `render.yaml`
   and documented for the manual dashboard path). **This is now the
   permanent, correct setup** — but it's the clearest lesson in the whole
   project: local testing and real production deployment are genuinely
   different tests, and something can pass every local check and still
   fail on first real deploy.
6. **Automated test suite** (pytest) — 40 tests as of Tier 2, covering
   auth, cross-user data isolation, exact four-fifths-rule boundary cases,
   CSV parsing edge cases, password reset, email verification, and
   Pydantic validation. Run with `pytest tests/ -v`.

**Also fixed during initial deployment:** Python 3.14 was Render's default
and broke `psycopg2-binary` (no compatible wheel) — pinned Python to 3.12
via `.python-version` file, which works across manual and Blueprint deploys.

---

## Tier 2 — DONE (password reset, verification, monitoring, validation)

All six items implemented and tested:

1. **Password reset** — stateless signed tokens (itsdangerous, no extra DB
   table). Token embeds a fingerprint of the current password hash, so it
   auto-invalidates once the password actually changes (tested: reusing a
   token after reset is rejected). 1-hour expiry.
2. **Email verification** — same stateless-token pattern, 3-day expiry,
   new `email_verified` column on `User` (migration generated and tested).
   **Deliberately non-blocking** — unverified users can still log in and
   use the tool; they see a banner with a resend button instead of being
   locked out. This was a considered trade-off (avoid locking out a real
   user during a live demo/pitch), not an oversight — worth revisiting once
   onboarding real paying clients rather than demoing.
3. **Real email sending** (Flask-Mail, standard SMTP) — has a dev-mode
   fallback that logs the email instead of sending when `MAIL_SERVER` isn't
   configured, which is how the reset/verification flows got tested without
   real credentials. **Honest, still-open gap: never tested against a real
   SMTP server or real inbox.** Needs real credentials set
   (`MAIL_SERVER`/`MAIL_USERNAME`/`MAIL_PASSWORD`/etc.) and a real send
   test before this is trustworthy for real users.
4. **Error monitoring (Sentry)** — wired in, activates only if `SENTRY_DSN`
   env var is set, otherwise does nothing. Not yet configured with a real
   Sentry project.
5. **Structured JSON logging** — verified real JSON output in production
   mode (human-readable in local dev). Every log line has timestamp, level,
   message, and context.
6. **Input validation (Pydantic)** — all `/api/auth/*` routes plus
   `/api/score`, `/api/insights`, `/api/clients` now validate against
   explicit schemas (`schemas.py`). Malformed requests get a clean 400 with
   field-level errors instead of crashing or silently misbehaving.

**Also done:** Gunicorn worker tuning (`--workers 2 --worker-class gthread
--threads 4 --timeout 120`), sized for Render's free-tier resource limits
and the AI call's latency.

---

## Frontend status

- **Public landing page** (`/`) — real design work: hero leads with an
  actual annotated four-fifths-rule finding (not a generic gradient),
  methodology section styled as a citation register, now includes a
  Pricing section (just added, matches the citation-list visual pattern).
- **The tool itself** (`/app`) — restructured from one long scrolling form
  into a tabbed layout: Data entry / Scorecard & insights / Saved clients,
  with a persistent left nav. Auto-switches to Results after running a
  scorecard.
- **Design tokens:** paper `#eef0ea`, ink `#151a23`, indigo `#25314f`
  (brand/primary), single amber accent `#b8892b`, Fraunces (serif,
  headlines) + Inter (body). Deliberately avoids AI-generated-design
  clichés (no cream+terracotta, no ALL-CAPS eyebrows, no identical-shadow
  card kit).

---

## Tier 3 — NOT STARTED (product maturity, planned)

This is the next phase whenever the founder is ready. In rough priority
order based on what's been discussed:

1. **Regression-based pay equity** — controlling for tenure, performance,
   role scope, not just level. This is what Trusaic's actual engine does;
   the current level-based comparison is a meaningfully simpler
   statistical approach. Biggest single gap versus being a "real" Trusaic
   competitor.
2. **HCM integrations** — pulling data automatically instead of CSV
   upload. Trusaic's biggest moat; hardest to replicate quickly.
3. **Flexible CSV column mapping** — currently requires exact template
   column names; a real customer's export won't match by default.
4. **Industry benchmarks** — comparing a company's scores to aggregate
   data across the client base. Needs 10+ real clients' data first before
   this is meaningful.
5. **Ongoing/ continuous monitoring** rather than one-off audits.
6. **Sentiment/culture surveys, board-ready reporting exports,
   dedicated-advisor workflow** — later-stage, mentioned in the original
   long-term roadmap.

---

## Known gaps — engineering side (tracked honestly, not hidden)

From the README's "What's still missing" section, current as of Tier 2:

- No audit log (who viewed/exported what, when)
- No account lockout after repeated failed logins (rate limiting slows
  brute force but doesn't lock accounts)
- No dependency vulnerability scanning (pip-audit/Dependabot)
- Email deliverability untested (see Tier 2 notes above)
- No industry benchmarks yet
- CSV column names must match template exactly
- Regression-based pay equity not implemented (see Tier 3)
- Redis needed for rate limiting before scaling past one gunicorn worker

## Known gaps — legal/business side (NOT engineering-fixable, flagged explicitly)

- **Kenya Data Protection Act 2019 compliance is unresolved.** Usawa
  processes sensitive personal data (gender/demographic + salary data) for
  people who aren't its direct customers (its clients' employees), which
  likely makes it a data processor under the Act with registration and
  DPA-agreement obligations. **A licensed Kenyan data protection/tech
  lawyer needs to review this before onboarding real client data at
  scale.** This was explicitly called out as potentially the actual
  blocker on monetization timeline, more urgent than any remaining code
  work. The founder said they'd handle this on their end ("concentrate on
  your end, I'll concentrate on mine") — engineering work has continued in
  parallel, but this legal review has not been confirmed as done.
- No payment processing integrated yet (no Stripe/Paystack/Flutterwave/
  M-Pesa) — pricing tiers are now on the landing page, but there's no way
  to actually charge anyone through the product yet.
- No formal Terms of Service / Privacy Policy / Data Processing Agreement
  documents exist yet (offered to draft a first pass for legal review,
  not yet done as of this writing).

---

## How to resume work

```bash
cd equity-scorecard-app
pip install -r requirements.txt --break-system-packages
export ANTHROPIC_API_KEY=your_key_here
export SECRET_KEY=any-random-string-for-local-dev
python3 app.py
# open http://localhost:5000
```

Run the test suite: `pytest tests/ -v` (should show 40 passed)

Full environment variable reference, deployment steps, and security/
methodology documentation all live in `README.md` — that file is the
detailed technical reference; this file is the project-level summary and
context anchor.

**Live production URL:** the founder's Render deployment (check Render
dashboard — service name `usawa`). GitHub-connected; pushing to `main`
auto-deploys.

---

## If you're an AI assistant picking this up in a new conversation

Read this whole file before doing anything. The founder has been
explicit, more than once, that security is foundational and that honesty
about what's tested versus untested matters more than sounding finished.
Match that standard: test claims before making them, flag trade-offs
explicitly, and don't let "it should work" substitute for "I verified it
works."
