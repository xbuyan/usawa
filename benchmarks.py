"""
The learning layer: cross-company benchmarks and mined patterns.

This is what makes the product get smarter as more companies use it.

Flow:
  1. CAPTURE — when a sharing user saves a report, an anonymized
     CompanySnapshot is extracted (no user_id, no company name — the
     capture function physically accepts neither).
  2. MATERIALIZIZE — cohort percentiles are precomputed into
     BenchmarkStats (one row per cohort x metric x percentile), so
     serving a comparison is an indexed point lookup, never a scan.
  3. MINE — LearnedPattern rows are recomputed from the feature store:
     associations between practices (condition metrics) and outcomes
     (pay gap, promotion equity...), kept only when the cohort is big
     enough to say something.
  4. SERVE — /api/benchmarks joins the user's scorecard against the
     right cohort (own industry+band first, falling back to
     all-industries+band, then all-companies) with k-anonymity enforced
     at every level.

Privacy guarantees, in order of enforcement:
  - Snapshots contain no identifying columns at all (models.py).
  - Size is stored as a coarse band, never the raw number, so a company
    can't be picked out as "the only 7-person fintech".
  - No statistic is exposed for a cohort smaller than MIN_COHORT.
  - Sharing is opt-in per user; opting out stops future capture (already
    stored snapshots are aggregate-only and contain nothing identifying,
    but a user who opted in and contributed can email us for deletion —
    that's a support flow, not a code path, and should be documented in
    the privacy policy when there is one).

Scale path (the "millions of users" answer): percentiles are already
materialized and reads are one indexed query. The write path is where
scale actually lands, so recomputation is debounced and runs OFF the
request path: maybe_recompute enqueues the rebuild instead of running
it inline. Coordination is a Redis lock (SET NX EX, so a killed process
can't wedge materialization past the TTL) — with 2 gunicorn workers,
exactly one process rebuilds per debounce window, not two racing ones.
When Redis is unavailable the code degrades to the original per-process
debounce, and when TESTING it runs inline so tests can assert state
immediately. The rebuild functions are pure (rows in, stats out) — if
volume ever outgrows a daemon thread (e.g. a long rebuild starving the
worker's thread pool), swap the thread for a real RQ/Celery worker
pointing at the same functions without rewriting them.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import redis as redis_lib
from flask import current_app

from models import db, CompanySnapshot, BenchmarkStats, LearnedPattern

# --- Tuning constants ------------------------------------------------------
# k-anonymity floor: no cohort statistic or pattern is exposed below this
# many contributing companies. 5 balances honesty against usefulness for
# an early-stage dataset; raise it as the base grows.
MIN_COHORT = 5
# Size bands: raw employee counts are bucketed so re-identification via
# an exact headcount is impossible and cohorts stay meaningful.
SIZE_BANDS = [
    (50, "micro"),      # ≤ 50
    (200, "small"),     # 51–200
    (500, "medium"),    # 201–500
    (float("inf"), "large"),
]
METRICS = ["overall", "pay_equity", "promotion_equity", "hiring_funnel",
           "representation_pipeline", "job_language"]
PERCENTILES = [10, 25, 50, 75, 90]
# Patterns are mined from these condition metrics ("practices") against
# outcome metrics ("results"). Conditions are score-derived — the honest
# form of "companies with X hiring practice": the scorecard's stage-level
# four-fifths data and practice scores stand in for raw practice labels.
CONDITION_METRICS = ["hiring_funnel", "job_language", "representation_pipeline"]
OUTCOME_METRICS = ["pay_equity", "promotion_equity", "overall"]
# Correlation must clear this to be worth showing (either direction).
MIN_ABS_CORRELATION = 0.35

# Debounce window for materialization (per process). See scale note above.
RECOMPUTE_INTERVAL_SECONDS = 60
_last_recompute = 0.0

# Cross-process coordination for materialization. A single rebuild is
# short (seconds at current volumes) but the lock TTL deliberately
# outlives it: if a worker dies mid-rebuild, Redis expires the lock on
# its own and materialization is only delayed, never wedged.
RECOMPUTE_LOCK_KEY = "usawa:benchmarks:recompute-lock"
RECOMPUTE_LOCK_TTL_SECONDS = 90

# Sentinel returned by _acquire_recompute_lock when Redis is not
# configured or unreachable: proceed without a cross-process lock.
_NO_REDIS = object()


def _get_redis_client():
    """A redis client for cross-process locking, or _NO_REDIS when Redis
    isn't configured or isn't reachable right now. Locking is a scale
    optimization, not a correctness requirement (the per-process debounce
    still applies underneath it), so any connection problem here degrades
    silently rather than raising."""
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if not redis_url:
        return _NO_REDIS
    try:
        client = redis_lib.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return client
    except Exception:
        return _NO_REDIS


def _acquire_recompute_lock() -> bool:
    """True if this call won the right to recompute right now. SET NX EX
    means exactly one of N racing gunicorn workers wins per TTL window;
    the TTL (not an explicit release) is what bounds a dead worker's lock,
    matching the module docstring's crash-safety note. No Redis reachable
    -> True, so a Redis outage degrades to the pre-lock, per-process-only
    debounce rather than freezing benchmarks from ever recomputing."""
    client = _get_redis_client()
    if client is _NO_REDIS:
        return True
    try:
        return bool(
            client.set(RECOMPUTE_LOCK_KEY, "1", nx=True, ex=RECOMPUTE_LOCK_TTL_SECONDS)
        )
    except Exception:
        return True


def size_band_for(company_size) -> Optional[str]:
    """Maps a raw headcount to a coarse band. None when unusable — callers
    must not guess a band, since a wrong band poisons a cohort."""
    try:
        n = int(company_size)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    for upper, band in SIZE_BANDS:
        if n <= upper:
            return band
    return None


def _normalize_industry(industry: Optional[str]) -> Optional[str]:
    """Industries are free-text from the form. Normalize for cohorting:
    trimmed, lowercased, capped. None/empty stays None (the fallback
    cohort) — a fabricated industry label is worse than no label."""
    if not industry:
        return None
    cleaned = str(industry).strip().lower()[:100]
    return cleaned or None


# ---------------------------------------------------------------------------
# 1. Capture
# ---------------------------------------------------------------------------

def capture_snapshot(company_data: Dict, scorecard: Dict) -> Optional[CompanySnapshot]:
    """
    Extracts an anonymized snapshot from a saved report's form + scorecard.
    Returns the (uncommitted) CompanySnapshot, or None when there's nothing
    valid to capture — capture failing must never block saving a report.

    NOTE the signature: it takes the report payload only. There is no
    user parameter — by construction, nothing user-identifying can be
    written into a snapshot.
    """
    sub_scores = scorecard.get("sub_scores") or {}
    overall = scorecard.get("overall_score")
    if overall is None or not sub_scores:
        return None

    band = size_band_for(company_data.get("companySize") or company_data.get("company_size"))
    if not band:
        return None

    def _score(key: str) -> Optional[int]:
        v = sub_scores.get(key)
        return int(v) if isinstance(v, (int, float)) else None

    metrics = {
        "pay_gap_by_level": company_data.get("pay_gap_by_level") or {},
        "promotion": company_data.get("promotion") or {},
        "hiring_funnel": {
            "stage_four_fifths_ratios": ((scorecard.get("details") or {}).get("hiring_funnel") or {}).get(
                "stage_four_fifths_ratios", {}),
            "passes_four_fifths_rule": ((scorecard.get("details") or {}).get("hiring_funnel") or {}).get(
                "passes_four_fifths_rule"),
        },
        "representation_by_level": company_data.get("representation_by_level") or {},
        "time_to_promotion_months": (company_data.get("promotion") or {}).get("time_to_promotion_months") or {},
    }

    snapshot = CompanySnapshot(
        industry=_normalize_industry(company_data.get("industry")),
        size_band=band,
        overall_score=int(overall),
        pay_equity_score=_score("pay_equity"),
        promotion_equity_score=_score("promotion_equity"),
        hiring_funnel_score=_score("hiring_funnel"),
        representation_score=_score("representation_pipeline"),
        job_language_score=_score("job_language"),
        metrics_json=json.dumps(metrics),
        features_json=json.dumps({m: _score(m) for m in METRICS if m != "overall"}),
    )
    db.session.add(snapshot)
    return snapshot


# ---------------------------------------------------------------------------
# 2. Materialize cohort percentiles
# ---------------------------------------------------------------------------

def _percentile(sorted_values: List[float], pct: int) -> float:
    """Linear-interpolation percentile on a pre-sorted list (numpy-free so
    this stays importable anywhere in the app)."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)          # floor
    c = min(f + 1, len(sorted_values) - 1)
    return float(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f))


def _cohort_rows(industry: Optional[str], size_band: str):
    return CompanySnapshot.query.filter(
        CompanySnapshot.size_band == size_band,
        CompanySnapshot.industry == industry if industry is not None else CompanySnapshot.industry.is_(None),
    )


def recompute_benchmark_stats() -> Dict[str, int]:
    """
    Rebuilds BenchmarkStats + LearnedPattern rows from all snapshots.

    Cohort semantics (must match get_benchmarks_for_scorecard's fallback
    chain): industry=None in this table means "ALL companies in this size
    band regardless of industry" — the fallback cohort served when a
    user's industry cohort doesn't exist or is too small. It is NOT
    "companies with a NULL industry label"; those are simply part of the
    band-wide cohort.

    A cohort with fewer than MIN_COHORT contributing companies gets NO
    rows — absence in this table is the k-anonymity enforcement, not a
    UI convention.

    Returns counts, for logging/tests. Commits.
    """
    stats_written = 0
    patterns_written = 0

    industries = [row[0] for row in db.session.query(CompanySnapshot.industry).distinct().all()
                  if row[0] is not None]
    bands = [row[0] for row in db.session.query(CompanySnapshot.size_band).distinct().all()]

    BenchmarkStats.query.delete()
    LearnedPattern.query.delete()

    def _materialize_cohort(industry: Optional[str], band: str, rows: List[CompanySnapshot]) -> Tuple[int, int]:
        """Writes percentile rows + mined patterns for one cohort.
        Returns (stats_written, patterns_written)."""
        s_written = p_written = 0

        per_metric: Dict[str, List[int]] = {"overall": [r.overall_score for r in rows]}
        score_fields = {
            "pay_equity": "pay_equity_score",
            "promotion_equity": "promotion_equity_score",
            "hiring_funnel": "hiring_funnel_score",
            "representation_pipeline": "representation_score",
            "job_language": "job_language_score",
        }
        for metric, attr in score_fields.items():
            vals = [getattr(r, attr) for r in rows]
            vals = [v for v in vals if v is not None]
            if vals:
                per_metric[metric] = vals

        for metric, vals in per_metric.items():
            vals.sort()
            n = len(vals)
            if n < MIN_COHORT:
                continue  # k-anonymity: small cohorts materialize nothing
            for pct in PERCENTILES:
                db.session.add(BenchmarkStats(
                    industry=industry, size_band=band, metric=metric,
                    n_companies=n, percentile=pct,
                    value=round(_percentile(vals, pct), 2),
                ))
                s_written += 1

        # Features for pattern mining (parsed once per cohort).
        features = []
        for r in rows:
            try:
                features.append(json.loads(r.features_json))
            except (ValueError, TypeError):
                features.append({})
        p_written = _mine_patterns(industry, band, rows, features)
        return s_written, p_written

    for band in bands:
        band_rows = CompanySnapshot.query.filter_by(size_band=band).all()
        if not band_rows:
            continue

        # Industry-specific cohorts (within this band).
        for industry in industries:
            rows = [r for r in band_rows if r.industry == industry]
            if not rows:
                continue
            s, p = _materialize_cohort(industry, band, rows)
            stats_written += s
            patterns_written += p

        # Band-wide fallback cohort: every company in the band, industry
        # regardless. Stored under industry=None (see docstring above).
        s, p = _materialize_cohort(None, band, band_rows)
        stats_written += s
        patterns_written += p

    db.session.commit()
    return {"benchmark_stats": stats_written, "learned_patterns": patterns_written}


def maybe_recompute(force: bool = False) -> Optional[Dict[str, int]]:
    """Debounced wrapper around recompute_benchmark_stats — at most once
    per RECOMPUTE_INTERVAL_SECONDS per process, plus a Redis lock so at
    most one of the 2 gunicorn workers actually rebuilds per window (see
    module docstring). The rebuild itself runs on a background thread so
    the caller's request isn't held up by it, except:
      - force=True runs inline and returns the counts dict, so callers
        (and this module's own tests) can assert on the result.
      - under TESTING, everything runs inline for the same reason —
        tests should be able to assert the DB state immediately after
        calling this, not race a background thread.
    Returns the counts dict when a recompute ran inline, else None
    (including when a recompute was *started* in the background — its
    result isn't available to the caller)."""
    global _last_recompute
    now = time.monotonic()
    if not force and (now - _last_recompute) < RECOMPUTE_INTERVAL_SECONDS:
        return None
    if not force and not _acquire_recompute_lock():
        # Another worker already won this window's rebuild.
        return None
    _last_recompute = now

    try:
        testing = bool(current_app and current_app.config.get("TESTING"))
    except RuntimeError:
        # No app context (e.g. called from a script) - safest to run inline.
        testing = True

    if force or testing:
        return recompute_benchmark_stats()

    app = current_app._get_current_object()

    def _run():
        with app.app_context():
            try:
                recompute_benchmark_stats()
            except Exception:
                app.logger.exception("Background benchmark recompute failed.")

    threading.Thread(target=_run, daemon=True, name="benchmark-recompute").start()
    return None


# ---------------------------------------------------------------------------
# 3. Mine patterns
# ---------------------------------------------------------------------------

def _mine_patterns(industry: Optional[str], size_band: str,
                   rows: List[CompanySnapshot], features: List[Dict]) -> int:
    """
    For each (condition metric, outcome metric) pair, split the cohort at
    the condition's TRUE median (mean of the two middle values when the
    cohort size is even) and compare outcome distributions. Splitting at
    the upper-middle element instead would pack the median company into
    the low side, making every even-sized cohort split 4/2 or worse —
    which fails the both-sides-have-3 guard and mines nothing at all for
    cohorts of 5–6, exactly the k-anonymity floor where early data lives.
    The pattern
    is the difference in outcome medians plus a rank correlation; kept
    only when n >= MIN_COHORT, both sides have >= 3 companies (which, with
    a median split, means patterns effectively need n >= 6 even though
    stats materialize from 5), and the correlation clears
    MIN_ABS_CORRELATION. Written to LearnedPattern.
    Returns how many patterns were written.
    """
    outcome_getters = {
        "pay_equity": lambda r: r.pay_equity_score,
        "promotion_equity": lambda r: r.promotion_equity_score,
        "hiring_funnel": lambda r: r.hiring_funnel_score,
        "representation_pipeline": lambda r: r.representation_score,
        "overall": lambda r: r.overall_score,
    }
    condition_getters = {
        "hiring_funnel": lambda r: r.hiring_funnel_score,
        "job_language": lambda r: r.job_language_score,
        "representation_pipeline": lambda r: r.representation_score,
    }

    labels = {
        "hiring_funnel": "hiring funnel", "job_language": "job-language",
        "representation_pipeline": "representation pipeline",
        "pay_equity": "pay equity", "promotion_equity": "promotion equity",
        "overall": "overall equity",
    }

    written = 0
    n_total = len(rows)

    for cond in CONDITION_METRICS:
        cond_vals = [(i, condition_getters[cond](r)) for i, r in enumerate(rows)]
        cond_vals = [(i, v) for i, v in cond_vals if v is not None]
        if len(cond_vals) < MIN_COHORT:
            continue
        cond_sorted = sorted(v for _, v in cond_vals)
        if len(cond_sorted) % 2 == 1:
            median = float(cond_sorted[len(cond_sorted) // 2])
        else:
            median = (cond_sorted[len(cond_sorted) // 2 - 1]
                      + cond_sorted[len(cond_sorted) // 2]) / 2.0

        for outcome in OUTCOME_METRICS:
            if outcome == cond:
                continue
            low_idx = [i for i, v in cond_vals if v <= median]
            high_idx = [i for i, v in cond_vals if v > median]
            if len(low_idx) < 3 or len(high_idx) < 3:
                continue

            low_vals = [outcome_getters[outcome](rows[i]) for i in low_idx]
            high_vals = [outcome_getters[outcome](rows[i]) for i in high_idx]
            low_vals = [v for v in low_vals if v is not None]
            high_vals = [v for v in high_vals if v is not None]
            if len(low_vals) < 3 or len(high_vals) < 3:
                continue

            # Rank correlation over pairs where the outcome is known —
            # a NULL sub-score must shrink the sample, not crash the
            # recompute (spearman with mismatched xs/ys would TypeError).
            scored = [(i, v) for i, v in cond_vals
                      if outcome_getters[outcome](rows[i]) is not None]
            corr = _spearman(
                [v for _, v in scored],
                [outcome_getters[outcome](rows[i]) for i, _ in scored],
            ) if len(scored) >= 3 else None
            if corr is None or abs(corr) < MIN_ABS_CORRELATION:
                continue

            low_med = _median(low_vals)
            high_med = _median(high_vals)
            delta = round(high_med - low_med, 1)
            if delta == 0:
                continue

            direction = "higher" if delta > 0 else "lower"
            cond_label = (f"{labels[cond]} score above {int(median)}"
                          if delta > 0 else f"{labels[cond]} score at or below {int(median)}")
            statement = (
                f"In this cohort, companies with {cond_label} tend to show "
                f"{abs(delta)} points {direction} median {labels[outcome]} score than the rest."
            )
            db.session.add(LearnedPattern(
                industry=industry, size_band=size_band,
                condition_metric=cond, condition_label=cond_label,
                outcome_metric=outcome,
                correlation=round(corr, 3),
                outcome_delta_median=delta,
                n_companies=n_total,
                statement=statement,
            ))
            written += 1

    return written


def _median(values: List[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _spearman(xs: List[float], ys: List[float]) -> Optional[float]:
    """Spearman rank correlation, implemented directly (no scipy import
    needed here — keeps the learning layer dependency-light and fast).
    Returns None when a correlation isn't defined (all-equal input)."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None

    def _ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        ranks = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    rx, ry = _ranks(xs), _ranks(ys)
    n = len(xs)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    var_x = sum((a - mean_x) ** 2 for a in rx)
    var_y = sum((b - mean_y) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return None
    return cov / ((var_x ** 0.5) * (var_y ** 0.5))


# ---------------------------------------------------------------------------
# 4. Serve
# ---------------------------------------------------------------------------

def get_benchmarks_for_scorecard(scorecard: Dict, company_size=None,
                                 industry: Optional[str] = None,
                                 include_patterns: bool = True) -> Dict:
    """
    Builds the comparison payload for one user's scorecard: their percentile
    standing per metric in the best available cohort, plus (optionally) the
    cohort's learned patterns.

    Cohort fallback chain, in order:
      (industry, band) -> (None, band) -> (None, any band present)
    ...picking the first cohort that actually has rows for the metric.
    Every response says which cohort produced each number — a benchmark
    without its cohort label is how benchmarks start quietly lying.
    """
    band = size_band_for(company_size)
    norm_industry = _normalize_industry(industry)
    sub_scores = scorecard.get("sub_scores") or {}
    overall = scorecard.get("overall_score")

    metrics: Dict[str, Optional[int]] = {}
    if overall is not None:
        metrics["overall"] = int(overall)
    key_map = {
        "pay_equity": "pay_equity", "promotion_equity": "promotion_equity",
        "hiring_funnel": "hiring_funnel", "representation_pipeline": "representation_pipeline",
        "job_language": "job_language",
    }
    for k in key_map:
        v = sub_scores.get(k)
        if isinstance(v, (int, float)):
            metrics[k] = int(v)

    cohort_chain = []
    if band:
        if norm_industry:
            cohort_chain.append((norm_industry, band))
        cohort_chain.append((None, band))
    cohort_chain.append((None, None))  # any band

    comparisons = []
    any_cohort_found = False
    for metric, value in metrics.items():
        chosen = None
        for ind, bd in cohort_chain:
            q = BenchmarkStats.query.filter_by(metric=metric, percentile=50)
            q = q.filter(BenchmarkStats.industry == ind) if ind is not None else q.filter(
                BenchmarkStats.industry.is_(None))
            if bd is not None:
                q = q.filter(BenchmarkStats.size_band == bd)
            # bd None means "any band" — deliberately no size filter.
            row = q.first()
            if row and row.n_companies >= MIN_COHORT:
                chosen = (ind, bd, row)
                break
        if not chosen:
            comparisons.append({
                "metric": metric, "your_score": value,
                "available": False,
                "reason": "Not enough companies in any matching cohort yet "
                          f"(minimum {MIN_COHORT}). This unlocks as more companies opt in.",
            })
            continue

        ind, bd, row = chosen
        any_cohort_found = True
        percentile = _percentile_for_value(metric, ind, bd, value)
        stats_rows = _stats_rows(metric, ind, bd)
        comparisons.append({
            "metric": metric,
            "your_score": value,
            "available": True,
            "cohort": {
                "industry": ind,
                "size_band": bd,
                "n_companies": row.n_companies,
                "label": _cohort_label(ind, bd),
            },
            "cohort_median": row.value,
            "your_percentile": percentile,
            "percentiles": {str(r.percentile): r.value for r in stats_rows},
        })

    patterns = []
    if include_patterns and any_cohort_found:
        patterns = _patterns_for(metrics, band, norm_industry)

    return {
        "available": any_cohort_found,
        "min_cohort": MIN_COHORT,
        "comparisons": comparisons,
        "patterns": patterns,
    }


def _stats_rows(metric: str, industry: Optional[str], band: Optional[str]):
    q = BenchmarkStats.query.filter_by(metric=metric)
    q = q.filter(BenchmarkStats.industry == industry) if industry is not None else q.filter(
        BenchmarkStats.industry.is_(None))
    if band is not None:
        q = q.filter(BenchmarkStats.size_band == band)
    return q.all()


def _percentile_for_value(metric: str, industry: Optional[str], band: Optional[str],
                          value: Optional[int]) -> Optional[int]:
    """Interpolates the user's percentile within the cohort's stored
    percentile points. Coarse by design — we store 5 points, not the full
    distribution, deliberately: less stored data, and 5-point resolution
    is all a UI should claim anyway."""
    if value is None:
        return None
    rows = sorted(_stats_rows(metric, industry, band), key=lambda r: r.percentile)
    pts = [(r.percentile, r.value) for r in rows]
    if not pts:
        return None
    if value <= pts[0][1]:
        return pts[0][0]
    if value >= pts[-1][1]:
        return pts[-1][0]
    # Find the bracketing stored points and interpolate linearly between
    # them (on value -> percentile, since value is monotonic in percentile).
    for (p0, v0), (p1, v1) in zip(pts, pts[1:]):
        if v0 <= value <= v1:
            if v1 == v0:
                return int(round((p0 + p1) / 2))
            frac = (value - v0) / (v1 - v0)
            return int(round(p0 + frac * (p1 - p0)))
    return None


def _patterns_for(metrics: Dict[str, int], band: Optional[str], industry: Optional[str]) -> List[Dict]:
    """Learned patterns for the user's cohorts. Only patterns whose condition
    the user actually satisfies (or narrowly misses) are returned, so the
    feed is 'patterns that apply to you', not a data dump."""
    q = LearnedPattern.query
    if industry is not None:
        q = q.filter((LearnedPattern.industry == industry) | (LearnedPattern.industry.is_(None)))
    else:
        q = q.filter(LearnedPattern.industry.is_(None))
    if band is not None:
        q = q.filter(LearnedPattern.size_band == band)
    rows = q.all()

    out = []
    for p in rows:
        cond_value = metrics.get(p.condition_metric)
        if cond_value is None:
            continue
        above = "above" in p.condition_label
        applies = (cond_value > _label_threshold(p.condition_label)) if above \
            else (cond_value <= _label_threshold(p.condition_label))
        if applies:
            out.append({
                "statement": p.statement,
                "condition_metric": p.condition_metric,
                "outcome_metric": p.outcome_metric,
                "correlation": p.correlation,
                "n_companies": p.n_companies,
            })
    out.sort(key=lambda x: abs(x.get("correlation", 0)), reverse=True)
    return out[:3]


def _label_threshold(condition_label: str) -> int:
    """Extracts the numeric threshold from a condition_label like
    'hiring funnel score above 62'. Kept in lockstep with _mine_patterns'
    label format; a label that doesn't parse makes the pattern inapplicable
    rather than wrongly applicable."""
    import re
    m = re.search(r"(\d+)", condition_label)
    return int(m.group(1)) if m else -1


def _cohort_label(industry: Optional[str], band: Optional[str]) -> str:
    band_names = {"micro": "≤50 employees", "small": "51–200 employees",
                  "medium": "201–500 employees", "large": "500+ employees"}
    parts = []
    if industry:
        parts.append(industry)
    if band and band in band_names:
        parts.append(band_names[band])
    return "companies like yours (" + ", ".join(parts) + ")" if parts else "all participating companies"
