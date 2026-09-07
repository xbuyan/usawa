"""
DEI Scorecard — Scoring Engine

Implements the scoring logic from scoring_and_prompt_spec.md:
pay equity, promotion equity, hiring funnel, representation pipeline,
and job description language — each as a 0-100 score, rolled into
one overall score.

Usage:
    from dei_scorecard import calculate_scorecard

    result = calculate_scorecard(company_data)
    print(result["overall_score"])
"""

from typing import Dict, List, Optional
import re


# ---------------------------------------------------------------------------
# Helpers: threshold-based scoring
# ---------------------------------------------------------------------------

def _score_from_thresholds(value: float, thresholds: List[tuple]) -> int:
    """
    thresholds: list of (upper_bound, score), sorted ascending by upper_bound.
    Returns the score for the first bucket where value <= upper_bound.
    The last tuple should have upper_bound = float('inf') as a catch-all.
    """
    for upper_bound, score in thresholds:
        if value <= upper_bound:
            return score
    return thresholds[-1][1]


def _four_fifths_score(rate_a: float, rate_b: float) -> Dict:
    """
    Scores a selection-rate comparison against the EEOC "four-fifths rule"
    (29 CFR 1607.4(D)), the standard used in adverse-impact analysis for
    hiring, promotion, and other selection decisions: a selection rate for
    any group that is less than 4/5 (80%) of the rate for the group with
    the highest rate is generally regarded as evidence of adverse impact.

    This is a real regulatory screening tool used by the EEOC/OFCCP — not
    a legal conclusion by itself, but a widely recognized red-flag test,
    which is why it's used here as the basis for scoring instead of an
    arbitrary percentage-point cutoff.

    Returns the four-fifths ratio, whether it passes the rule, and a score
    that degrades further the worse the ratio gets below 0.8.
    """
    if rate_a <= 0 and rate_b <= 0:
        return {"ratio": 1.0, "passes_four_fifths_rule": True, "score": 100}

    higher = max(rate_a, rate_b)
    lower = min(rate_a, rate_b)
    ratio = (lower / higher) if higher > 0 else 1.0
    passes = ratio >= 0.8

    if ratio >= 0.8:
        # Linear from 80 (right at the line) to 100 (perfectly equal)
        score = round(80 + (ratio - 0.8) / 0.2 * 20)
    elif ratio >= 0.6:
        # Clearly fails the rule but not severely — 40 to 79
        score = round(40 + (ratio - 0.6) / 0.2 * 39)
    elif ratio >= 0.4:
        # Fails badly — 15 to 39
        score = round(15 + (ratio - 0.4) / 0.2 * 24)
    else:
        # Severe adverse impact — 0 to 14
        score = round(max(0, ratio / 0.4 * 14))

    return {"ratio": round(ratio, 3), "passes_four_fifths_rule": passes, "score": score}


# ---------------------------------------------------------------------------
# 1. Pay Equity Score
# ---------------------------------------------------------------------------

def pay_equity_score(pay_gap_by_level: Dict[str, float]) -> Dict:
    """
    pay_gap_by_level: e.g. {"IC": 3.0, "Manager": 8.0, "Director": 14.0}
    Each value is a % gap: (avg_pay_group_A - avg_pay_group_B) / avg_pay_group_A * 100
    Calculated within the same level/role — never company-wide.

    Threshold basis: there is no single legal cutoff for pay gap percentage
    (unlike selection rates, which have the four-fifths rule). These bands
    reflect common practice among pay equity consultancies and academic
    literature, where an unexplained gap of roughly 5% or more (after
    controlling for role/level/tenure) is typically treated as the point
    worth investigating and remediating, and gaps above ~15% are considered
    severe. Treat this as a screening heuristic, not a legal determination —
    a real pay equity finding requires controlling for legitimate factors
    (performance, tenure, location) that this simplified level-based
    comparison does not fully capture.

    Returns per-level scores and an overall pay score (average, or worst-level
    weighted — using average of levels here, worst level flagged separately).
    """
    thresholds = [
        (2, 100),
        (5, 80),
        (10, 60),
        (15, 35),
        (float("inf"), 15),
    ]

    level_scores = {
        level: _score_from_thresholds(abs(gap), thresholds)
        for level, gap in pay_gap_by_level.items()
    }

    overall = round(sum(level_scores.values()) / len(level_scores)) if level_scores else 100
    worst_level = min(level_scores, key=level_scores.get) if level_scores else None

    return {
        "score": overall,
        "by_level": level_scores,
        "worst_level": worst_level,
    }


# ---------------------------------------------------------------------------
# 2. Promotion Equity Score
# ---------------------------------------------------------------------------

def promotion_equity_score(
    promotions_a: int,
    eligible_a: int,
    promotions_b: int,
    eligible_b: int,
    time_to_promotion_months: Optional[Dict[str, float]] = None,
) -> Dict:
    """
    Compares promotion rate between two groups (e.g. group_a = women,
    group_b = men). eligible_* = headcount eligible for promotion in that group.

    Scored against the EEOC four-fifths rule (see _four_fifths_score) —
    promotion is a selection decision, so the same adverse-impact screening
    test the EEOC applies to hiring applies here too.

    time_to_promotion_months: optional, e.g. {"group_a": 18, "group_b": 26}
    Reported for context — the four-fifths rule doesn't cover time-to-promotion
    directly, but a large gap here is often the more persuasive evidence in
    practice even when promotion rates look acceptable.
    """
    rate_a = promotions_a / eligible_a if eligible_a else 0
    rate_b = promotions_b / eligible_b if eligible_b else 0

    ff = _four_fifths_score(rate_a, rate_b)

    result = {
        "score": ff["score"],
        "promotion_rate_a": round(rate_a * 100, 1),
        "promotion_rate_b": round(rate_b * 100, 1),
        "gap_percentage_points": round(abs(rate_a - rate_b) * 100, 1),
        "four_fifths_ratio": ff["ratio"],
        "passes_four_fifths_rule": ff["passes_four_fifths_rule"],
    }

    if time_to_promotion_months:
        result["time_to_promotion_months"] = time_to_promotion_months
        a, b = time_to_promotion_months.get("group_a"), time_to_promotion_months.get("group_b")
        if a is not None and b is not None and min(a, b) > 0:
            result["time_to_promotion_gap_percent"] = round(abs(a - b) / min(a, b) * 100, 1)

    return result


# ---------------------------------------------------------------------------
# 3. Hiring Funnel Score
# ---------------------------------------------------------------------------

def hiring_funnel_score(
    funnel_a: Dict[str, int],
    funnel_b: Dict[str, int],
    stages: Optional[List[str]] = None,
) -> Dict:
    """
    funnel_a / funnel_b: e.g. {"applied": 500, "interviewed": 120, "offered": 20, "hired": 15}
    stages: order of funnel stages; defaults to standard order.

    Each stage transition (e.g. applied -> interviewed) is a selection
    decision, scored against the EEOC four-fifths rule. The overall score
    is driven by the worst-scoring stage, since a single stage that fails
    the rule is a real adverse-impact flag regardless of how the other
    stages look.
    """
    stages = stages or ["applied", "interviewed", "offered", "hired"]

    conversions_a, conversions_b, stage_results = {}, {}, {}

    for i in range(1, len(stages)):
        prev, curr = stages[i - 1], stages[i]
        conv_a = funnel_a[curr] / funnel_a[prev] if funnel_a.get(prev) else 0
        conv_b = funnel_b[curr] / funnel_b[prev] if funnel_b.get(prev) else 0
        key = f"{prev}_to_{curr}"
        conversions_a[key] = round(conv_a * 100, 1)
        conversions_b[key] = round(conv_b * 100, 1)
        stage_results[key] = _four_fifths_score(conv_a, conv_b)

    if stage_results:
        worst_stage = min(stage_results, key=lambda k: stage_results[k]["score"])
        score = stage_results[worst_stage]["score"]
        passes_overall = all(r["passes_four_fifths_rule"] for r in stage_results.values())
    else:
        worst_stage, score, passes_overall = None, 100, True

    return {
        "score": score,
        "conversions_group_a": conversions_a,
        "conversions_group_b": conversions_b,
        "stage_four_fifths_ratios": {k: v["ratio"] for k, v in stage_results.items()},
        "stage_passes_four_fifths": {k: v["passes_four_fifths_rule"] for k, v in stage_results.items()},
        "worst_stage": worst_stage,
        "passes_four_fifths_rule": passes_overall,
    }


# ---------------------------------------------------------------------------
# 4. Representation Pipeline Score ("leaky pipeline")
# ---------------------------------------------------------------------------

def representation_pipeline_score(
    representation_by_level: Dict[str, float],
    level_order: Optional[List[str]] = None,
) -> Dict:
    """
    representation_by_level: % of group A at each level,
    e.g. {"IC": 48, "Manager": 32, "Director": 19, "Exec": 8}
    level_order: ordered from entry to top; defaults to dict order.

    Unlike selection-rate metrics (hiring, promotion), there is no
    regulatory test for representation drop-off — this is a descriptive
    "leaky pipeline" signal, not a compliance measure. It's useful for
    spotting where representation erodes across levels, but shouldn't be
    presented to stakeholders as a legal or regulatory finding the way the
    four-fifths-based scores can be.
    """
    thresholds = [
        (10, 100),
        (20, 70),
        (35, 40),
        (float("inf"), 15),
    ]

    levels = level_order or list(representation_by_level.keys())
    entry_pct = representation_by_level[levels[0]]
    top_pct = representation_by_level[levels[-1]]
    drop = entry_pct - top_pct

    score = _score_from_thresholds(drop, thresholds)

    return {
        "score": score,
        "entry_level_percent": entry_pct,
        "top_level_percent": top_pct,
        "drop_percentage_points": round(drop, 1),
        "by_level": representation_by_level,
    }


# ---------------------------------------------------------------------------
# 5. Job Description Language Score
# ---------------------------------------------------------------------------

# Starting word lists — expand/tune with real research lists over time.
MASCULINE_CODED_WORDS = {
    "ninja", "rockstar", "dominant", "aggressive", "competitive",
    "fearless", "superior", "driven", "assertive", "decisive",
}
FEMININE_CODED_WORDS = {
    "supportive", "collaborative", "nurturing", "compassionate",
    "warm", "dependable", "loyal", "interpersonal",
}


def job_description_language_score(
    job_postings: List[str],
    weight_factor: float = 15,
) -> Dict:
    """
    job_postings: list of job description text strings.
    Flags an imbalanced mix of gender-coded words across all postings —
    an imbalance is the signal, not any single word's presence.
    """
    masculine_count, feminine_count, total_words = 0, 0, 0

    for text in job_postings:
        words = re.findall(r"[a-zA-Z']+", text.lower())
        total_words += len(words)
        masculine_count += sum(1 for w in words if w in MASCULINE_CODED_WORDS)
        feminine_count += sum(1 for w in words if w in FEMININE_CODED_WORDS)

    flagged_count = masculine_count + feminine_count
    imbalance_ratio = (
        abs(masculine_count - feminine_count) / flagged_count if flagged_count else 0
    )

    penalty = (flagged_count / total_words * 100 * weight_factor) if total_words else 0
    score = max(0, round(100 - penalty))

    return {
        "score": score,
        "masculine_coded_word_count": masculine_count,
        "feminine_coded_word_count": feminine_count,
        "imbalance_ratio": round(imbalance_ratio, 2),
        "total_words_scanned": total_words,
    }


# ---------------------------------------------------------------------------
# Overall Score
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "pay_equity": 0.30,
    "promotion_equity": 0.25,
    "hiring_funnel": 0.20,
    "representation_pipeline": 0.15,
    "job_language": 0.10,
}


def calculate_scorecard(company_data: Dict, weights: Optional[Dict[str, float]] = None) -> Dict:
    """
    company_data expected keys (all optional — missing sections are skipped
    and weights are redistributed proportionally across what's available):

      pay_gap_by_level: Dict[str, float]
      promotion: {
          "promotions_a": int, "eligible_a": int,
          "promotions_b": int, "eligible_b": int,
          "time_to_promotion_months": Dict[str, float]  # optional
      }
      hiring_funnel: {"funnel_a": Dict, "funnel_b": Dict, "stages": List[str]}  # stages optional
      representation_by_level: Dict[str, float]
      job_postings: List[str]
    """
    weights = weights or DEFAULT_WEIGHTS
    scores = {}
    details = {}

    if "pay_gap_by_level" in company_data:
        result = pay_equity_score(company_data["pay_gap_by_level"])
        scores["pay_equity"] = result["score"]
        details["pay_equity"] = result

    if "promotion" in company_data:
        p = company_data["promotion"]
        result = promotion_equity_score(
            p["promotions_a"], p["eligible_a"],
            p["promotions_b"], p["eligible_b"],
            p.get("time_to_promotion_months"),
        )
        scores["promotion_equity"] = result["score"]
        details["promotion_equity"] = result

    if "hiring_funnel" in company_data:
        f = company_data["hiring_funnel"]
        result = hiring_funnel_score(f["funnel_a"], f["funnel_b"], f.get("stages"))
        scores["hiring_funnel"] = result["score"]
        details["hiring_funnel"] = result

    if "representation_by_level" in company_data:
        result = representation_pipeline_score(company_data["representation_by_level"])
        scores["representation_pipeline"] = result["score"]
        details["representation_pipeline"] = result

    if "job_postings" in company_data:
        result = job_description_language_score(company_data["job_postings"])
        scores["job_language"] = result["score"]
        details["job_language"] = result

    # Redistribute weights proportionally across whatever sections are present
    active_weight_total = sum(weights[k] for k in scores if k in weights)
    overall_score = None
    if active_weight_total > 0:
        overall_score = round(
            sum(scores[k] * weights[k] for k in scores if k in weights) / active_weight_total
        )

    return {
        "overall_score": overall_score,
        "sub_scores": scores,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    example_company = {
        "pay_gap_by_level": {"IC": 3, "Manager": 8, "Director": 14},
        "promotion": {
            "promotions_a": 8, "eligible_a": 60,
            "promotions_b": 15, "eligible_b": 65,
            "time_to_promotion_months": {"group_a": 26, "group_b": 18},
        },
        "hiring_funnel": {
            "funnel_a": {"applied": 500, "interviewed": 120, "offered": 20, "hired": 15},
            "funnel_b": {"applied": 700, "interviewed": 200, "offered": 40, "hired": 32},
        },
        "representation_by_level": {"IC": 48, "Manager": 32, "Director": 19, "Exec": 8},
        "job_postings": [
            "We're looking for a rockstar ninja engineer who is aggressive and driven.",
            "Join our collaborative and supportive team of dependable engineers.",
        ],
    }

    scorecard = calculate_scorecard(example_company)
    print(json.dumps(scorecard, indent=2))
