"""
Seed-script tests: the seeder is the first-deploy experience for the
learning layer, so its guarantees are pinned like any other data path —

- The generated dataset actually SERVES: cohorts materialize, benchmarks
  come back available, and mined patterns exist (a seeder whose demo
  cohorts are all below the k-anonymity floor would seed nothing).
- Determinism: fixed RNG seed means two generations are identical, so
  demos are reproducible and diffable.
- Privacy ordering: it refuses when real (unseeded) snapshots exist, and
  refuses a plain re-run instead of silently doubling cohort sizes.
- It cleans up only after itself: --clear removes seeded rows and never
  touches real captures.
- Generated rows go through capture_snapshot, so they're structurally
  identical to real captures (and carry no identity fields).
"""

import pytest

import seed_demo_data
from models import db, CompanySnapshot, BenchmarkStats, LearnedPattern


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_real_snapshot(industry="software", band="small", overall=61):
    s = CompanySnapshot(
        industry=industry, size_band=band, overall_score=overall,
        pay_equity_score=70, hiring_funnel_score=60,
        metrics_json="{}", features_json="{}", seeded=False,
    )
    db.session.add(s)
    db.session.commit()
    return s


@pytest.fixture
def seeded(app):
    """Runs the seeder inside the test app context; returns its result."""
    with app.app_context():
        result = seed_demo_data.seed_demo_data()
        assert result["ok"], result.get("reason")
        return result


# ---------------------------------------------------------------------------
# The dataset itself
# ---------------------------------------------------------------------------

def test_generated_population_shape():
    """4 industries x 2 bands x 6 companies = 48 demo companies."""
    companies = seed_demo_data.generate_demo_companies()
    assert len(companies) == 48
    for c in companies:
        assert set(c) == {"form", "scorecard"}
        assert c["form"]["companySize"] > 0
        assert c["form"]["industry"] in seed_demo_data.INDUSTRY_PROFILES
        sc = c["scorecard"]
        assert isinstance(sc["overall_score"], int)
        assert set(sc["sub_scores"]) == {
            "pay_equity", "promotion_equity", "hiring_funnel",
            "representation_pipeline", "job_language"}
        # Scores stay in the plausible 0-100 band.
        for v in list(sc["sub_scores"].values()) + [sc["overall_score"]]:
            assert 0 <= v <= 100


def test_generation_is_deterministic():
    a = seed_demo_data.generate_demo_companies()
    b = seed_demo_data.generate_demo_companies()
    assert a == b


def test_seeded_rows_are_structurally_identical_to_real_captures(seeded):
    """Demo rows are written through capture_snapshot — same columns, same
    normalization — with only the seeded flag distinguishing them."""
    rows = CompanySnapshot.query.all()
    assert rows, "seeder must insert snapshots"
    assert all(r.seeded for r in rows)
    # capture_snapshot normalized the industry labels.
    assert {r.industry for r in rows} <= set(seed_demo_data.INDUSTRY_PROFILES)
    assert all(r.size_band in ("small", "medium") for r in rows)
    # No identity columns exist on snapshots at all (structural privacy).
    cols = {c.name for c in CompanySnapshot.__table__.columns}
    assert "user_id" not in cols and "company_name" not in cols


# ---------------------------------------------------------------------------
# The seeder actually makes the feature work end to end
# ---------------------------------------------------------------------------

def test_seeded_data_materializes_and_serves(app, seeded):
    with app.app_context():
        assert seeded["inserted"] == 48
        counts = seeded["counts"]
        assert counts["benchmark_stats"] > 0, "percentiles must materialize"
        assert counts["learned_patterns"] > 0, "demo must show mined patterns"

        # The serving path returns available comparisons for a demo-matching
        # scorecard — this is the "fresh deploy shows a working feature" test.
        from benchmarks import get_benchmarks_for_scorecard
        scorecard = {"overall_score": 70, "sub_scores": {
            "pay_equity": 72, "promotion_equity": 68, "hiring_funnel": 75,
            "representation_pipeline": 66, "job_language": 70}}
        payload = get_benchmarks_for_scorecard(
            scorecard, company_size=120, industry="software")
        assert payload["available"] is True
        available = [c for c in payload["comparisons"] if c["available"]]
        assert available, "software/small cohort (n=6) must be servable"
        for c in available:
            assert c["cohort"]["n_companies"] >= 5
        assert payload["patterns"], "seeded cohorts must yield patterns"


def test_seeded_data_is_deterministic_across_reseed(app, seeded):
    """--force reseeding reproduces the exact same dataset."""
    with app.app_context():
        first = sorted(
            (r.industry, r.size_band, r.overall_score,
             r.pay_equity_score, r.hiring_funnel_score)
            for r in CompanySnapshot.query.all())

        result = seed_demo_data.seed_demo_data(force=True)
        assert result["ok"] and result["replaced"] == 48

        second = sorted(
            (r.industry, r.size_band, r.overall_score,
             r.pay_equity_score, r.hiring_funnel_score)
            for r in CompanySnapshot.query.all())
        assert first == second


# ---------------------------------------------------------------------------
# The honesty rules
# ---------------------------------------------------------------------------

def test_seeder_refuses_when_real_data_exists(app):
    with app.app_context():
        _make_real_snapshot()
        result = seed_demo_data.seed_demo_data()
        assert result["ok"] is False and result["refused"] is True
        assert "real" in result["reason"].lower()
        # Nothing was inserted.
        assert CompanySnapshot.query.filter_by(seeded=True).count() == 0


def test_plain_rerun_refuses_instead_of_silently_doubling(app, seeded):
    with app.app_context():
        result = seed_demo_data.seed_demo_data()
        assert result["ok"] is False and result["refused"] is True
        assert result.get("already_seeded") is True
        assert "--force" in result["reason"]
        # Cohort size unchanged — no silent doubling.
        assert CompanySnapshot.query.filter_by(seeded=True).count() == 48


def test_force_respects_the_real_data_guard(app):
    """--force replaces demo rows, but NEVER when real rows exist."""
    with app.app_context():
        _make_real_snapshot()
        result = seed_demo_data.seed_demo_data(force=True)
        assert result["ok"] is False
        real = CompanySnapshot.query.filter_by(seeded=False).first()
        assert real is not None  # untouched


def test_clear_removes_only_seeded_rows(app, seeded):
    with app.app_context():
        _make_real_snapshot()
        result = seed_demo_data.clear_demo_data()
        assert result["ok"] and result["removed"] == 48
        remaining = CompanySnapshot.query.all()
        assert len(remaining) == 1
        assert remaining[0].seeded is False  # the real capture survives
        # Cohort tables were rebuilt from what remains; the lone real
        # snapshot is below MIN_COHORT, so it materializes nothing (k=5).
        assert BenchmarkStats.query.count() == 0


def test_clear_on_empty_database_is_safe(app):
    with app.app_context():
        result = seed_demo_data.clear_demo_data()
        assert result["ok"] and result["removed"] == 0
