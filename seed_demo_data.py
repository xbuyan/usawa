"""
Seed demo companies so the learning layer has data on a fresh deploy.

A brand-new deployment has zero CompanySnapshots, which means /api/benchmarks
honestly reports "not enough companies in any matching cohort yet" for every
metric — correct privacy behavior, terrible first impression. This script
fills the cohorts with clearly-labeled synthetic companies so the feature
demos properly from minute one.

The honesty rules (all enforced, not aspirational):
  - Demo rows are written through benchmarks.capture_snapshot, so they are
    structurally identical to real captures — and they are flagged
    `seeded=True`, which real captures never are.
  - Seeding REFUSES to run when any real (unseeded) snapshot exists. Demo
    data must never silently blend into cohorts that also contain real
    contributions — "companies like yours" that includes fake companies is
    a lie. Past your first real user, the move is `--clear`, not `--force`.
  - `--clear` removes ONLY rows where seeded=True. Real captures are
    structurally unreachable by this script.
  - Generation is deterministic (fixed RNG seed): two runs produce the
    exact same dataset, so a demo is reproducible and diffable.

Usage:
    flask db upgrade                 # tables must exist first (see README)
    export SECRET_KEY=...            # app.py refuses to start without one
    python3 seed_demo_data.py        # seed (refuses if any snapshots exist)
    python3 seed_demo_data.py --force   # replace previous demo rows
    python3 seed_demo_data.py --clear   # remove demo rows, recompute
    python3 seed_demo_data.py --status  # what's in the learning layer now

The seeder is deliberately NOT silently idempotent: a second plain run
refuses and points at --force / --clear, so "ran it twice" can never
quietly double a cohort's n and distort every percentile.
"""

import argparse
import random
import sys
from typing import Dict, List

from app import app, db
from benchmarks import capture_snapshot, recompute_benchmark_stats
from models import BenchmarkStats, CompanySnapshot, LearnedPattern

# Fixed seed → identical dataset on every run/machine. Change this number
# and you change the demo dataset; don't do it casually.
RNG_SEED = 20260922

# ---------------------------------------------------------------------------
# The synthetic population
# ---------------------------------------------------------------------------
# Each demo company gets a "practice strength" s ∈ [0, 1]. Metrics are then
# derived from s with per-industry weighting, so cohorts show realistic,
# DIFFERENT structure: software's pattern is funnel→pay-equity, healthcare's
# is representation→promotion, retail's job-language→overall, and finance is
# deliberately noisy (its weak correlations should mostly fail the 0.35
# threshold — a demo where everything correlates with everything reads as
# fake, and "no pattern found" is an honest result the engine must be
# allowed to produce).
INDUSTRY_PROFILES = {
    "software":   {"driver": "hiring_funnel",         "weight": 0.62, "noise": 3.0, "base": 46},
    "healthcare": {"driver": "representation_pipeline", "weight": 0.58, "noise": 3.5, "base": 44},
    "retail":     {"driver": "job_language",          "weight": 0.55, "noise": 4.0, "base": 42},
    "finance":    {"driver": "hiring_funnel",         "weight": 0.30, "noise": 9.0, "base": 45},
}

# (industry, size band, count) — 6 companies per cell. Industry cohorts get
# n=6: above MIN_COHORT=5 so percentiles materialize, and above the ≥6
# effective pattern-mining floor so industry-level patterns show in demos.
# Band-wide (all-industry) cohorts get n=12, exercising the fallback chain.
POPULATION = [
    (industry, band, 6)
    for industry in INDUSTRY_PROFILES
    for band in ("small", "medium")
]

BAND_SIZES = {"small": (55, 190), "medium": (210, 480)}


def generate_demo_companies() -> List[Dict]:
    """Builds the deterministic demo population as capture-ready payloads:
    [{form, scorecard}]. No company names — snapshots can't hold them."""
    rng = random.Random(RNG_SEED)
    companies = []

    for industry, band, count in POPULATION:
        profile = INDUSTRY_PROFILES[industry]
        lo, hi = BAND_SIZES[band]
        for _ in range(count):
            s = rng.random()                      # this company's practice strength
            size = rng.randint(lo, hi)

            def _jitter(spread):
                return rng.uniform(-spread, spread)

            funnel = _clip(profile["base"] + 42 * s + _jitter(4))
            language = _clip(profile["base"] + 38 * s + _jitter(5))
            repr_pipe = _clip(profile["base"] + 40 * s + _jitter(5))

            # The driver metric pulls its paired outcome; everything else
            # wanders mildly with s. This is what makes different cohorts
            # exhibit different mined patterns.
            driver_val = {"hiring_funnel": funnel,
                          "job_language": language,
                          "representation_pipeline": repr_pipe}[profile["driver"]]
            pay = _clip(profile["base"] + profile["weight"] * driver_val
                        + 0.18 * funnel + _jitter(profile["noise"]))
            promotion = _clip(profile["base"] + profile["weight"] * driver_val
                              + 0.20 * repr_pipe + _jitter(profile["noise"]))

            sub_scores = {
                "pay_equity": round(pay),
                "promotion_equity": round(promotion),
                "hiring_funnel": round(funnel),
                "representation_pipeline": round(repr_pipe),
                "job_language": round(language),
            }
            # Consistent with how the real scorecard behaves: overall is a
            # rounded mean of the sub-scores (weights differ in the real
            # engine, but the seeder must not fabricate a magic number).
            overall = round(sum(sub_scores.values()) / len(sub_scores))

            companies.append({
                "form": {"companySize": size, "industry": industry},
                "scorecard": {"overall_score": overall, "sub_scores": sub_scores},
            })
    return companies


def _clip(v: float, lo: int = 5, hi: int = 98) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _counts() -> Dict[str, int]:
    return {
        "real_snapshots": CompanySnapshot.query.filter_by(seeded=False).count(),
        "seeded_snapshots": CompanySnapshot.query.filter_by(seeded=True).count(),
        "benchmark_stats": BenchmarkStats.query.count(),
        "learned_patterns": LearnedPattern.query.count(),
    }


def seed_demo_data(force: bool = False) -> Dict:
    """Inserts the demo population and materializes cohorts. Returns a
    result dict {ok, inserted, counts, statements} — the tests assert on
    this, the CLI prints it. Refuses (ok=False) when real snapshots exist."""
    real = CompanySnapshot.query.filter_by(seeded=False).count()
    if real:
        return {
            "ok": False,
            "refused": True,
            "reason": (
                f"{real} real (unseeded) snapshot(s) already exist. Demo data must "
                "not blend into cohorts that contain real contributions — run "
                "`python3 seed_demo_data.py --clear` to remove demo rows instead."
            ),
            "counts": _counts(),
        }

    already = CompanySnapshot.query.filter_by(seeded=True).count()
    if already and not force:
        # Not silently idempotent on purpose: re-running plain would double
        # every cohort's n and distort all percentiles. Be explicit instead.
        return {
            "ok": False,
            "refused": True,
            "already_seeded": True,
            "reason": (
                f"{already} demo snapshot(s) already seeded. Run with --force to "
                "replace them, or --clear to remove them."
            ),
            "counts": _counts(),
        }

    replaced = 0
    if force:
        # Replace the previous demo population wholesale. Only seeded rows
        # are reachable here (the refusal above guarantees no real rows).
        replaced = CompanySnapshot.query.filter_by(seeded=True).delete()
        db.session.commit()

    inserted = 0
    for payload in generate_demo_companies():
        snapshot = capture_snapshot(payload["form"], payload["scorecard"])
        if snapshot is None:
            continue  # would mean a generator bug — the payloads are complete
        snapshot.seeded = True
        inserted += 1
    db.session.commit()

    counts = recompute_benchmark_stats()
    statements = [p.statement for p in LearnedPattern.query.order_by(
        LearnedPattern.correlation.desc()).limit(3).all()]
    return {"ok": True, "inserted": inserted, "replaced": replaced,
            "counts": {**_counts(), **counts}, "statements": statements}


def clear_demo_data() -> Dict:
    """Removes ONLY seeded rows, then rebuilds cohort tables from whatever
    remains (which may legitimately be nothing — that's honest)."""
    n = CompanySnapshot.query.filter_by(seeded=True).delete()
    db.session.commit()
    counts = recompute_benchmark_stats()
    return {"ok": True, "removed": n, "counts": {**_counts(), **counts}}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--force", action="store_true",
                        help="replace previously seeded demo rows with a fresh set")
    parser.add_argument("--clear", action="store_true",
                        help="remove seeded demo rows and recompute")
    parser.add_argument("--status", action="store_true",
                        help="show learning-layer counts and exit")
    args = parser.parse_args()

    with app.app_context():
        try:
            if args.status:
                print(_counts())
                return 0
            result = clear_demo_data() if args.clear else seed_demo_data(force=args.force)
        except Exception as e:
            # Most likely cause: tables don't exist yet (fresh DB without
            # `flask db upgrade`). Say that instead of a raw traceback.
            print(f"error: {e}\n(hint: run `flask db upgrade` first?)", file=sys.stderr)
            return 1

        if not result.get("ok"):
            print(f"REFUSED: {result['reason']}")
            return 1

        if args.clear:
            print(f"Removed {result['removed']} seeded demo snapshot(s).")
        else:
            verb = "Replaced" if args.force else "Seeded"
            print(f"{verb} {result['inserted']} demo companies "
                  f"(deterministic, RNG_SEED={RNG_SEED}).")
        print(f"Learning layer now: {result['counts']}")
        for s in result.get("statements", []):
            print(f"  · {s}")
        if not args.clear:
            print("Done. /api/benchmarks now serves comparisons for demo-matching scorecards.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
