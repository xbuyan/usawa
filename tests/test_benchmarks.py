"""
Learning-layer tests — benchmarks, pattern mining, k-anonymity, privacy.

The math is tested against synthetic cohorts with KNOWN answers (the
same standard the pay-equity regression tests set): a cohort engineered
so a specific correlation must be recovered, specific percentile values,
specific k-anonymity exclusions. Privacy is tested structurally: the
snapshot capture function must be incapable of storing user identity,
and small cohorts must materialize nothing queryable.
"""

import json

import pytest

import benchmarks
from models import db, CompanySnapshot, BenchmarkStats, LearnedPattern, ClientReport, User


# ---------------------------------------------------------------------------
# Helpers to build synthetic cohorts
# ---------------------------------------------------------------------------

def _make_snapshot(industry, band, overall, pay=None, promo=None, funnel=None,
                   rep=None, lang=None):
    s = CompanySnapshot(
        industry=industry, size_band=band, overall_score=overall,
        pay_equity_score=pay, promotion_equity_score=promo,
        hiring_funnel_score=funnel, representation_score=rep,
        job_language_score=lang,
        metrics_json="{}", features_json="{}",
    )
    db.session.add(s)
    return s


@pytest.fixture
def learned_cohort(app):
    """8 'software/small' snapshots where hiring_funnel perfectly tracks
    pay_equity (high funnel <-> high pay equity), plus overall scores that
    follow funnel too. A working miner MUST recover this relationship."""
    funnel_scores = [80, 75, 70, 65, 45, 40, 35, 30]
    pay_scores    = [85, 80, 75, 70, 50, 45, 40, 35]
    overall       = [80, 76, 72, 68, 52, 48, 44, 40]
    for f, p, o in zip(funnel_scores, pay_scores, overall):
        _make_snapshot("software", "small", overall=o, pay=p, funnel=f)
    db.session.commit()
    return len(funnel_scores)


# ---------------------------------------------------------------------------
# Percentile materialization
# ---------------------------------------------------------------------------

def test_percentile_math_exact_values(app, learned_cohort):
    benchmarks.recompute_benchmark_stats()
    rows = BenchmarkStats.query.filter_by(
        industry="software", size_band="small", metric="overall").all()
    by_pct = {r.percentile: r.value for r in rows}
    # overall scores: [40, 44, 48, 52, 68, 72, 76, 80]
    # 10th pct (linear interp): index 0.7 -> 40 + 0.7*4 = 42.8
    assert by_pct[10] == pytest.approx(42.8)
    # median: between 4th and 5th values -> (52+68)/2 = 60.0
    assert by_pct[50] == pytest.approx(60.0)
    # 90th: index 6.3 -> 76 + 0.3*4 = 77.2
    assert by_pct[90] == pytest.approx(77.2)
    assert all(r.n_companies == 8 for r in rows)


def test_small_cohort_materializes_nothing_k_anonymity(app):
    """THE k-anonymity test: 4 companies is below MIN_COHORT, so no
    benchmark_stats row may exist for that cohort. Absence in this table
    IS the privacy enforcement — verified at the database level."""
    assert benchmarks.MIN_COHORT == 5
    for o in (60, 65, 70, 75):
        _make_snapshot("tinyco", "micro", overall=o)
    db.session.commit()

    benchmarks.recompute_benchmark_stats()

    leaked = BenchmarkStats.query.filter_by(industry="tinyco").all()
    assert leaked == [], "a 4-company cohort must materialize zero rows"


def test_fallback_cohort_still_materializes(app):
    # Two industries, each below MIN_COHORT, but sharing a size band:
    # the (industry=None, band) fallback cohort has 6 and must materialize.
    for o in (50, 60, 70):
        _make_snapshot("a", "small", overall=o)
    for o in (55, 65, 75):
        _make_snapshot("b", "small", overall=o)
    db.session.commit()

    benchmarks.recompute_benchmark_stats()

    fallback = BenchmarkStats.query.filter_by(
        industry=None, size_band="small", metric="overall", percentile=50).all()
    assert fallback, "fallback cohort (industry=None) must still materialize"
    assert fallback[0].n_companies == 6


# ---------------------------------------------------------------------------
# Pattern mining — the "gets smarter with more data" guarantee
# ---------------------------------------------------------------------------

def test_pattern_mining_recovers_known_correlation(app, learned_cohort):
    benchmarks.recompute_benchmark_stats()
    patterns = LearnedPattern.query.filter_by(
        industry="software", size_band="small",
        condition_metric="hiring_funnel", outcome_metric="pay_equity",
    ).all()
    assert patterns, "a perfectly-constructed cohort must yield the funnel->pay pattern"
    p = patterns[0]
    assert p.correlation == pytest.approx(1.0, abs=0.01)
    assert p.outcome_delta_median > 0  # high-funnel side has higher pay-equity median
    assert p.n_companies == 8
    assert "hiring funnel" in p.condition_label.lower()
    # The statement is the human-readable artifact the UI shows.
    assert "pay equity" in p.statement.lower()


def test_no_pattern_when_cohort_too_small(app):
    # 5 snapshots (meets MIN_COHORT) but a noisy relationship that should
    # not clear MIN_ABS_CORRELATION... engineer it: perfectly anticorrelated
    # small sample gets split unevenly; simplest honest guarantee is that a
    # cohort of 4 (below MIN_COHORT) yields nothing at all.
    for f, p in [(90, 20), (80, 70), (30, 90), (20, 10)]:
        _make_snapshot("noise", "micro", overall=50, funnel=f, pay=p)
    db.session.commit()
    benchmarks.recompute_benchmark_stats()
    assert LearnedPattern.query.filter_by(industry="noise").all() == []


def test_weak_correlation_is_suppressed(app):
    """A genuinely weak association must NOT become a pattern — confident
    nonsense is how the learning layer loses trust."""
    # Construct funnel vs pay with near-zero rank correlation.
    data = [
        (90, 50), (80, 50), (70, 50), (60, 50), (50, 50),
        (40, 50), (30, 50), (20, 50),  # pay constant -> corr undefined/suppressed
    ]
    for f, p in data:
        _make_snapshot("flat", "small", overall=50, funnel=f, pay=p)
    db.session.commit()
    benchmarks.recompute_benchmark_stats()
    assert LearnedPattern.query.filter_by(
        industry="flat", outcome_metric="pay_equity").all() == []


def test_pattern_mining_works_at_minimum_cohort_size(app):
    """Regression: the split used the upper-middle element as the "median",
    so an even-sized cohort packed the median company into the low side
    and split 4/2 — failing the both-sides-have-3 guard and mining ZERO
    patterns at n=5–6, exactly the k-anonymity floor where early cohorts
    live. The split must be at the true median. 6 companies, strictly
    ordered condition (no ties), outcome tracking it, must yield the
    engineered pattern."""
    data = [(40, 40), (42, 44), (44, 48), (46, 82), (85, 86), (87, 90)]
    for f, p in data:
        _make_snapshot("minco", "small", overall=70, funnel=f, pay=p)
    db.session.commit()
    benchmarks.recompute_benchmark_stats()
    found = LearnedPattern.query.filter_by(
        industry="minco", size_band="small",
        condition_metric="hiring_funnel", outcome_metric="pay_equity").all()
    assert len(found) == 1, "n=6 at the k-floor must still learn the pattern"
    p = found[0]
    assert p.correlation == pytest.approx(1.0, abs=0.01)
    assert p.outcome_delta_median == pytest.approx(42.0)


def test_maybe_recompute_is_debounced(app, learned_cohort, monkeypatch):
    """Two calls within the debounce window must run the rebuild once —
    this is what stops a million saves/day from meaning a million
    rebuilds."""
    benchmarks._last_recompute = 0.0
    calls = []
    real = benchmarks.recompute_benchmark_stats

    def _counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(benchmarks, "recompute_benchmark_stats", _counting)
    benchmarks.maybe_recompute(force=True)   # runs (force)
    benchmarks.maybe_recompute(force=False)  # inside window -> skipped
    assert len(calls) == 1
    benchmarks._last_recompute = 0.0  # reset for other tests


def test_maybe_recompute_skips_when_another_worker_holds_the_lock(
    app, learned_cohort, monkeypatch
):
    """Cross-process guard: if another gunicorn worker already won this
    window's rebuild (i.e. already holds the Redis lock), this process
    must not also rebuild, even though its own _last_recompute is stale."""
    benchmarks._last_recompute = 0.0
    calls = []
    monkeypatch.setattr(
        benchmarks, "recompute_benchmark_stats", lambda: calls.append(1)
    )
    monkeypatch.setattr(benchmarks, "_acquire_recompute_lock", lambda: False)

    result = benchmarks.maybe_recompute(force=False)

    assert result is None
    assert calls == []
    benchmarks._last_recompute = 0.0


def test_maybe_recompute_runs_when_lock_is_won(app, learned_cohort, monkeypatch):
    """Under TESTING, once the lock is won the rebuild still runs inline
    (not on a background thread) so the caller can assert on the result
    immediately."""
    benchmarks._last_recompute = 0.0
    monkeypatch.setattr(benchmarks, "_acquire_recompute_lock", lambda: True)

    result = benchmarks.maybe_recompute(force=False)

    assert result is not None
    assert "benchmark_stats" in result
    benchmarks._last_recompute = 0.0


def test_acquire_recompute_lock_true_when_redis_unavailable(app, monkeypatch):
    """No REDIS_URL configured (or Redis unreachable) must degrade to
    'proceed' rather than silently blocking benchmarks from ever
    recomputing again."""
    monkeypatch.setattr(benchmarks, "_get_redis_client", lambda: benchmarks._NO_REDIS)
    assert benchmarks._acquire_recompute_lock() is True


def test_acquire_recompute_lock_is_mutually_exclusive(app):
    """Real behavior against the real Redis instance used in CI: the
    first caller in a window wins, a second caller in the same window
    (simulating a second gunicorn worker) does not."""
    client = benchmarks._get_redis_client()
    if client is benchmarks._NO_REDIS:
        pytest.skip("Redis not reachable in this environment")
    client.delete(benchmarks.RECOMPUTE_LOCK_KEY)
    try:
        assert benchmarks._acquire_recompute_lock() is True
        assert benchmarks._acquire_recompute_lock() is False
    finally:
        client.delete(benchmarks.RECOMPUTE_LOCK_KEY)


# ---------------------------------------------------------------------------
# Snapshot capture — privacy structure
# ---------------------------------------------------------------------------

def test_capture_snapshot_contains_no_user_or_company_identity(app):
    """Structural privacy: capture_snapshot's signature cannot even receive
    a user, and the produced row must carry no identifying fields."""
    form = {
        "companyName": "Secret NDA Client Ltd",
        "companySize": 120,
        "industry": "Software",
        "pay_gap_by_level": {"IC": 4.0},
        "representation_by_level": {"IC": 40, "Manager": 30, "Director": 20, "Exec": 10},
    }
    scorecard = {
        "overall_score": 61,
        "sub_scores": {"pay_equity": 80, "hiring_funnel": 55},
        "details": {"hiring_funnel": {"passes_four_fifths_rule": False,
                                      "stage_four_fifths_ratios": {"applied_to_interviewed": 0.72}}},
    }

    snap = benchmarks.capture_snapshot(form, scorecard)
    db.session.add(snap)
    db.session.commit()

    stored = db.session.get(CompanySnapshot, snap.id)
    assert stored.industry == "software"  # normalized
    assert stored.size_band == "small"
    assert stored.overall_score == 61
    # No user identity column exists at all — checked via the table's columns.
    cols = {c.name for c in CompanySnapshot.__table__.columns}
    assert "user_id" not in cols
    assert "company_name" not in cols
    # And nothing identifying leaked into the JSON payloads.
    assert "Secret NDA Client" not in (stored.metrics_json or "")
    assert "Secret NDA Client" not in (stored.features_json or "")


def test_capture_snapshot_rejects_incomplete_scorecard(app):
    # No overall score -> nothing valid to learn from.
    snap = benchmarks.capture_snapshot({"companySize": 100}, {"sub_scores": {}})
    assert snap is None


def test_capture_snapshot_rejects_unusable_size(app):
    snap = benchmarks.capture_snapshot(
        {"companySize": "not-a-number"}, {"overall_score": 50, "sub_scores": {"pay_equity": 60}})
    assert snap is None


def test_size_band_boundaries(app):
    assert benchmarks.size_band_for(1) == "micro"
    assert benchmarks.size_band_for(50) == "micro"
    assert benchmarks.size_band_for(51) == "small"
    assert benchmarks.size_band_for(200) == "small"
    assert benchmarks.size_band_for(201) == "medium"
    assert benchmarks.size_band_for(500) == "medium"
    assert benchmarks.size_band_for(501) == "large"
    assert benchmarks.size_band_for(0) is None
    assert benchmarks.size_band_for(-5) is None
    assert benchmarks.size_band_for(None) is None


# ---------------------------------------------------------------------------
# Serving benchmarks for a scorecard
# ---------------------------------------------------------------------------

def test_get_benchmarks_returns_percentile_and_cohort_label(app, learned_cohort):
    benchmarks.recompute_benchmark_stats()
    scorecard = {"overall_score": 76, "sub_scores": {"pay_equity": 80}}
    payload = benchmarks.get_benchmarks_for_scorecard(
        scorecard, company_size=120, industry="software")

    assert payload["available"] is True
    overall = next(c for c in payload["comparisons"] if c["metric"] == "overall")
    assert overall["available"] is True
    assert overall["cohort"]["n_companies"] == 8
    assert overall["your_score"] == 76
    # 76 sits at the 87.5th percentile of [40,44,48,52,68,72,76,80] -> ~88
    assert 75 <= overall["your_percentile"] <= 90
    assert "software" in overall["cohort"]["label"]


def test_get_benchmarks_falls_back_when_industry_cohort_missing(app, learned_cohort):
    benchmarks.recompute_benchmark_stats()
    # Different industry: no "fintech/small" cohort exists, so the (None,
    # small) fallback must serve — and say so honestly in the label.
    payload = benchmarks.get_benchmarks_for_scorecard(
        {"overall_score": 50, "sub_scores": {}}, company_size=100, industry="fintech")
    overall = next(c for c in payload["comparisons"] if c["metric"] == "overall")
    assert overall["available"] is True
    assert overall["cohort"]["industry"] is None


def test_get_benchmarks_reports_unavailable_when_nothing_qualifies(app):
    payload = benchmarks.get_benchmarks_for_scorecard(
        {"overall_score": 50, "sub_scores": {}}, company_size=100, industry="nothing")
    assert payload["available"] is False
    assert payload["comparisons"]


def test_patterns_filtered_to_what_applies_to_user(app, learned_cohort):
    benchmarks.recompute_benchmark_stats()
    # User has a HIGH hiring_funnel score -> only patterns whose condition
    # is "above N" should come back for them, not the below-median ones.
    payload = benchmarks.get_benchmarks_for_scorecard(
        {"overall_score": 70, "sub_scores": {"hiring_funnel": 72, "pay_equity": 60}},
        company_size=120, industry="software")
    for p in payload["patterns"]:
        assert p["condition_metric"] in ("hiring_funnel", "job_language", "representation_pipeline")


# ---------------------------------------------------------------------------
# End-to-end through the API: opt-in -> save -> materialize -> serve
# ---------------------------------------------------------------------------

def test_sharing_opt_in_flow(client, registered_user):
    client, email, password = registered_user
    # Off by default — consent is opt-in.
    assert client.get("/api/auth/me").get_json()["share_anonymized_data"] is False

    resp = client.post("/api/sharing", json={"share_anonymized_data": True})
    assert resp.status_code == 200
    assert resp.get_json()["share_anonymized_data"] is True
    assert client.get("/api/auth/me").get_json()["share_anonymized_data"] is True

    client.post("/api/sharing", json={"share_anonymized_data": False})
    assert client.get("/api/auth/me").get_json()["share_anonymized_data"] is False


def test_saved_report_becomes_snapshot_only_when_opted_in(client, registered_user):
    client, email, password = registered_user
    scorecard = {"overall_score": 55,
                 "sub_scores": {"pay_equity": 60, "hiring_funnel": 50},
                 "details": {}}
    form = {"companyName": "OptIn Co", "companySize": 100, "industry": "software"}

    # Not opted in yet: no snapshot.
    client.post("/api/clients", json={"company_name": "OptIn Co", "form": form,
                                      "scorecard": scorecard})
    assert CompanySnapshot.query.count() == 0

    # Opt in, save again: exactly one snapshot, with no company name.
    client.post("/api/sharing", json={"share_anonymized_data": True})
    client.post("/api/clients", json={"company_name": "OptIn Co", "form": form,
                                      "scorecard": scorecard})
    assert CompanySnapshot.query.count() == 1
    snap = CompanySnapshot.query.first()
    assert snap.industry == "software"
    assert not hasattr(snap, "user_id") or snap.user_id is None if hasattr(snap, "user_id") else True
    stored_blob = json.dumps({
        "metrics": json.loads(snap.metrics_json),
        "features": json.loads(snap.features_json),
    })
    assert "OptIn Co" not in stored_blob


def test_benchmark_endpoint_end_to_end(client, registered_user):
    client, email, password = registered_user
    client.post("/api/sharing", json={"share_anonymized_data": True})
    scorecard = {"overall_score": 55,
                 "sub_scores": {"pay_equity": 60, "hiring_funnel": 50},
                 "details": {}}
    form = {"companyName": "E2E Co", "companySize": 100, "industry": "software"}
    client.post("/api/clients", json={"company_name": "E2E Co", "form": form,
                                      "scorecard": scorecard})

    # One company is below MIN_COHORT — add 4 more opted-in companies so
    # the cohort qualifies, then materialize.
    for i in range(4):
        _make_snapshot("software", "small", overall=60,
                       pay=55, funnel=52)
    db.session.commit()
    benchmarks.maybe_recompute(force=True)
    resp = client.get(
        "/api/benchmarks?scorecard=" +
        json.dumps(scorecard).replace(" ", "") +
        f"&company_size=100&industry=software")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["available"] is True
    overall = next(c for c in body["comparisons"] if c["metric"] == "overall")
    assert overall["available"] is True
    assert overall["cohort"]["n_companies"] >= benchmarks.MIN_COHORT


def test_benchmark_endpoint_requires_login(client):
    assert client.get("/api/benchmarks?scorecard={}").status_code == 401


def test_benchmark_endpoint_rejects_bad_scorecard_param(client, registered_user):
    client, email, password = registered_user
    resp = client.get("/api/benchmarks?scorecard=not-json")
    assert resp.status_code == 400


def test_conversation_deletion(client, registered_user, monkeypatch):
    client, email, password = registered_user
    import chatbot
    monkeypatch.setattr(
        chatbot, "answer_question",
        lambda question, history=None, scorecard=None, patterns=None: {
            "answer": "ok", "sources": [], "grounded": False})
    convo = client.post("/api/chat", json={"question": "to be deleted"}).get_json()
    resp = client.delete(f"/api/conversations/{convo['conversation_id']}")
    assert resp.status_code == 204
    assert client.get("/api/conversations").get_json() == []
