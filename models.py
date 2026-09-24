"""
Database models. Uses SQLAlchemy so the same code runs against SQLite
locally (zero setup) and Postgres in production (set DATABASE_URL) without
any code changes — only the connection string differs.
"""

from datetime import datetime, timezone, timedelta

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Organization(db.Model):
    """
    A team/company workspace. Every user belongs to exactly one
    Organization — solo signups get one auto-created for them (see
    auth.register()); org-mates share visibility into each other's
    ClientReport and AuditLog rows via a join on User.organization_id,
    rather than each report row carrying its own "shared with" list.

    Deliberately no direct relationship/cascade declared here from
    Organization to User: an Organization outliving all its members (the
    last member leaves, or is the org itself being wound down some other
    way) is a decision for whatever feature handles that, not an ORM
    side effect of a user row disappearing.
    """
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    # Every user belongs to exactly one Organization (see Organization's
    # docstring for the sharing model this enables). NOT NULL is the end
    # state; a table with pre-existing users can't get there in a single
    # step (see migration a3f8b1c92d47 for why — same NOT-NULL-migration
    # lesson as email_verified, applied to a column that needs real
    # per-row backfill data, not a constant).
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    organization = db.relationship("Organization", backref=db.backref("members", lazy=True))
    password_hash = db.Column(db.String(255), nullable=False)
    organization_name = db.Column(db.String(255), nullable=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Account lockout — rate limiting (see extensions.py) slows brute force
    # by IP, but a distributed/slow attacker can stay under the per-IP
    # limit while still hammering one account. This adds a second,
    # per-account layer: after too many consecutive failures, the account
    # itself is locked for a cooldown window regardless of source IP.
    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    # Learning-layer consent. Default False — the benchmarks feature is
    # opt-in, not assumed. When False, this user's saved reports never
    # become CompanySnapshots, and /api/benchmarks still works (they can
    # see community stats; they just don't contribute to them).
    share_anonymized_data = db.Column(db.Boolean, nullable=False, default=False)

    # When this user accepted the Terms of Service at signup. Nullable on
    # purpose: accounts created before this consent gate existed have no
    # recorded acceptance, and recording NULL is the honest state —
    # backfilling a fake timestamp would claim consent that was never given.
    terms_accepted_at = db.Column(db.DateTime, nullable=True)

    reports = db.relationship("ClientReport", backref="owner", lazy=True, cascade="all, delete-orphan")

    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_MINUTES = 15

    @staticmethod
    def _utcnow_naive() -> datetime:
        # Plain db.DateTime columns strip tzinfo on write (confirmed via
        # SQLite; Postgres without timezone=True behaves the same way), so
        # a value read back from the DB is always naive. Comparing that
        # against an aware datetime.now(timezone.utc) raises TypeError —
        # this was caught by an actual test, not spotted by inspection.
        # Storing and comparing naive-but-UTC consistently avoids it.
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > self._utcnow_naive()

    def register_failed_login(self) -> None:
        """Call after a wrong-password attempt for this user. Locks the
        account once MAX_FAILED_ATTEMPTS consecutive failures are reached."""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= self.MAX_FAILED_ATTEMPTS:
            self.locked_until = self._utcnow_naive() + timedelta(minutes=self.LOCKOUT_MINUTES)

    def register_successful_login(self) -> None:
        """Call after a correct-password login. Clears the failure count
        and any lock, so a legitimate login fully resets the counter."""
        self.failed_login_attempts = 0
        self.locked_until = None

    def set_password(self, raw_password: str) -> None:
        # scrypt (Werkzeug's default) is a strong, slow-by-design hash —
        # appropriate for password storage, unlike fast hashes like plain SHA256.
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)


class ClientReport(db.Model):
    __tablename__ = "client_reports"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    company_name = db.Column(db.String(255), nullable=False)
    saved_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    form_json = db.Column(db.Text, nullable=False)
    scorecard_json = db.Column(db.Text, nullable=False)
    insights_json = db.Column(db.Text, nullable=True)


class CompanySnapshot(db.Model):
    """
    The atomic unit of the learning layer: one anonymized snapshot of one
    company's scorecard at one point in time.

    Privacy is structural, not promised:
      - No user_id column. There is deliberately NO way to join a snapshot
        back to the account that produced it — not "hard to find", absent.
      - company_name is stored NOT here but only in the owner's ClientReport
        (which the snapshot's contributing user can already see). What's
        kept is industry, size band, and the aggregate metrics — the shapes
        needed for cross-company pattern learning, nothing more.
    Everything is submitted through benchmarks.py, which enforces
    k-anonymity before any cohort statistic ever becomes queryable, and
    buckets size into bands so a lone company can't be re-identified by
    "the only 5-person fintech in the cohort".
    """
    __tablename__ = "company_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    # Nullable on purpose: one-off scorecards ("just exploring") shouldn't
    # fabricate an industry label that then pollutes cohort matching.
    industry = db.Column(db.String(100), nullable=True, index=True)
    size_band = db.Column(db.String(20), nullable=False, index=True)  # micro/small/medium/large
    # Scores at snapshot time — the facts patterns are mined from.
    overall_score = db.Column(db.Integer, nullable=False)
    pay_equity_score = db.Column(db.Integer, nullable=True)
    promotion_equity_score = db.Column(db.Integer, nullable=True)
    hiring_funnel_score = db.Column(db.Integer, nullable=True)
    representation_score = db.Column(db.Integer, nullable=True)
    job_language_score = db.Column(db.Integer, nullable=True)
    # Raw practice metrics (aggregates, not person-level rows). JSON keeps
    # this flexible as the scoring engine evolves; benchmarks.py reads it.
    metrics_json = db.Column(db.Text, nullable=False)
    # Features used by the pattern miner. Stored denormalized so mining
    # never has to re-parse metrics_json per row (million-row math is
    # batch work, and re-parsing JSON per row is exactly how that gets slow).
    features_json = db.Column(db.Text, nullable=False)
    # True when this row was written by seed_demo_data.py rather than
    # captured from an opted-in user's report. Demo data is clearly labeled
    # (the seeder can be re-run and can clean up after itself), and it must
    # never be silently indistinguishable from real contributions — that's
    # how demo rows end up permanently baked into a production cohort.
    # See seed_demo_data.py: recompute() is skipped when real (unseeded)
    # snapshots exist, because mixing demo data into real cohorts and then
    # presenting it as "companies like yours" would be a lie.
    seeded = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class BenchmarkStats(db.Model):
    """
    Precomputed cohort statistics — materialized, queryable, cheap.

    Computing percentiles from raw snapshots on every request would make
    each scorecard run scan the whole snapshots table — fine at 100
    snapshots, quadratic at a million. This table is the cache layer:
    rebuilt incrementally as snapshots accumulate, read on every request.

    One row = one (cohort definition) x (metric) x (percentile point).
    Denormalized by design: a request reads exactly the rows it needs,
    with no joins and no runtime grouping.
    """
    __tablename__ = "benchmark_stats"

    id = db.Column(db.Integer, primary_key=True)
    # NULL industry means "all industries" (the fallback cohort when an
    # industry-specific cohort doesn't exist yet — which it won't early on).
    industry = db.Column(db.String(100), nullable=True)
    size_band = db.Column(db.String(20), nullable=False)
    metric = db.Column(db.String(64), nullable=False)  # overall, pay_equity, ...
    n_companies = db.Column(db.Integer, nullable=False)  # cohort size for this metric
    percentile = db.Column(db.Integer, nullable=False)   # 10 / 25 / 50 / 75 / 90
    value = db.Column(db.Float, nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        db.Index("ix_benchmark_cohort_metric", "industry", "size_band", "metric", "percentile"),
    )


class LearnedPattern(db.Model):
    """
    A mined, human-readable learning-layer output.

    One row = one cohort x one metric pattern, e.g.:
      "Companies in software, small size band, with hiring_funnel_score
       below 50, show a median pay_equity_score 22 points lower than
       peers with hiring_funnel_score of 70+."

    Mined from snapshots only when the cohort has enough data (see
    benchmarks.py thresholds) — a sparse pattern is worse than none,
    because a confident-sounding correlation on 4 companies is how a
    recommendation engine loses an HR team's trust permanently.
    """
    __tablename__ = "learned_patterns"

    id = db.Column(db.Integer, primary_key=True)
    industry = db.Column(db.String(100), nullable=True)
    size_band = db.Column(db.String(20), nullable=False)
    condition_metric = db.Column(db.String(64), nullable=False)   # e.g. hiring_funnel
    condition_label = db.Column(db.String(255), nullable=False)   # human phrase, e.g. "hiring funnel below 50"
    outcome_metric = db.Column(db.String(64), nullable=False)     # e.g. pay_equity
    # Correlation strength between condition and outcome across the cohort
    # (-1..1). Stored, not recomputed, so the UI can rank patterns cheaply.
    correlation = db.Column(db.Float, nullable=False)
    outcome_delta_median = db.Column(db.Float, nullable=False)    # outcome gap (points) between the two sides
    n_companies = db.Column(db.Integer, nullable=False)           # sample behind this pattern
    statement = db.Column(db.Text, nullable=False)                # display sentence for the UI
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        db.Index("ix_patterns_cohort", "industry", "size_band", "condition_metric"),
    )


class Conversation(db.Model):
    """
    One assistant conversation. Scoped to user_id like every other
    user-owned resource in this app (same pattern as ClientReport).
    """
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False, default="New conversation")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    messages = db.relationship("ChatMessage", backref="conversation", lazy=True, cascade="all, delete-orphan",
                               order_by="ChatMessage.created_at")


class ChatMessage(db.Model):
    """
    One turn in a conversation. role is 'user' or 'assistant' — the
    assistant row stores which KB documents grounded the answer so the UI
    can show sources, and so repeated questions with no grounding can be
    spotted and turned into new KB entries (the knowledge base grows from
    real usage, which is the whole point of it).
    """
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)  # 'user' | 'assistant'
    content = db.Column(db.Text, nullable=False)
    # JSON array of {doc_id, title} for assistant messages; NULL for user rows.
    sources_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class AuditLog(db.Model):
    """
    Durable, queryable record of who accessed or changed sensitive data,
    and when. Distinct from the structured JSON application logs
    (logging_config.py) on purpose: application logs go to stdout and are
    only as durable as whatever log retention the hosting platform gives
    you for free, aren't easily queryable per-user, and — before this —
    didn't cover read access at all (only saves/deletes got a log line).
    A real audit trail for a tool handling pay/demographic data needs to
    survive log rotation and answer "who looked at this client's data,
    and when" directly from the database.

    No cascade delete from User: deliberately, an account deletion
    feature (not yet built) should have to decide explicitly what happens
    to that user's audit trail rather than silently losing it as a side
    effect of an unrelated ORM cascade.
    """
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False, index=True)
    resource_type = db.Column(db.String(64), nullable=True)
    resource_id = db.Column(db.String(64), nullable=True)
    detail = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
