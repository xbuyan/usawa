"""
CSV aggregation — turns one-row-per-person data into the aggregate shapes
calculate_scorecard() expects. Python port of the same logic used in the
in-browser prototype, so behavior stays identical between versions.
"""

from typing import Dict, List, Tuple

from csv_columns import remap_rows

LEVEL_ORDER = ["IC", "Manager", "Director", "Exec"]
STAGE_ORDER = ["applied", "interviewed", "offered", "hired"]


def _average(values: List[float]):
    return sum(values) / len(values) if values else None


def _normalize_group(g: str) -> str:
    return "a" if (g or "").strip().lower() == "a" else "b"


def _normalize_level(level: str):
    for l in LEVEL_ORDER:
        if l.lower() == (level or "").strip().lower():
            return l
    return None


def aggregate_employee_rows(rows: List[Dict]) -> Dict:
    """
    rows: list of dicts with keys employee_id, level, group, salary,
    promotion_eligible, promoted, months_to_promotion (strings, as read from CSV).
    Optional: tenure_months (or tenure_years) and performance_rating — used
    only for the supplementary regression-adjusted pay gap (see
    pay_equity_regression.py); their absence doesn't affect anything else.
    Column names are matched flexibly (see csv_columns.py) — the exact
    template names above are canonical, but common real-world spellings
    ("Employee ID", "Job Level", "Base Salary", etc.) are also accepted.
    Raises ValueError if a required column can't be found under any known
    spelling.
    """
    rows = remap_rows(rows, kind="employee")
    by_level = {level: {"a": [], "b": []} for level in LEVEL_ORDER}
    eligible_a = eligible_b = promoted_a = promoted_b = 0
    ttp_a, ttp_b = [], []
    skipped = []
    regression_input_rows = []

    for i, row in enumerate(rows):
        level = _normalize_level(row.get("level"))
        group = _normalize_group(row.get("group"))
        try:
            salary = float(row.get("salary", ""))
        except (ValueError, TypeError):
            salary = None

        if not level or salary is None:
            skipped.append(row.get("employee_id") or f"row {i + 2}")
            continue

        by_level[level][group].append(salary)

        # Optional fields for regression — tenure may arrive as months or
        # years (see csv_columns.py); years is converted here so the
        # regression module only ever deals in months.
        tenure_months = row.get("tenure_months")
        if tenure_months in (None, ""):
            tenure_years = row.get("tenure_years")
            try:
                tenure_months = float(tenure_years) * 12
            except (TypeError, ValueError):
                tenure_months = None
        else:
            try:
                tenure_months = float(tenure_months)
            except (TypeError, ValueError):
                tenure_months = None

        try:
            performance_rating = float(row.get("performance_rating"))
        except (TypeError, ValueError):
            performance_rating = None

        regression_input_rows.append({
            "level": level, "group": group, "salary": salary,
            "tenure_months": tenure_months, "performance_rating": performance_rating,
        })

        eligible = (row.get("promotion_eligible") or "").strip().lower() == "yes"
        promoted = (row.get("promoted") or "").strip().lower() == "yes"

        if eligible:
            if group == "a":
                eligible_a += 1
            else:
                eligible_b += 1

        if promoted:
            if group == "a":
                promoted_a += 1
            else:
                promoted_b += 1
            try:
                months = float(row.get("months_to_promotion", ""))
                (ttp_a if group == "a" else ttp_b).append(months)
            except (ValueError, TypeError):
                pass

    pay_gap_by_level = {}
    rep_by_level = {}

    for level in LEVEL_ORDER:
        a_vals, b_vals = by_level[level]["a"], by_level[level]["b"]
        avg_a, avg_b = _average(a_vals), _average(b_vals)
        if avg_a is not None and avg_b is not None and avg_a > 0:
            pay_gap_by_level[level] = ((avg_a - avg_b) / avg_a) * 100
        total = len(a_vals) + len(b_vals)
        if total > 0:
            rep_by_level[level] = (len(a_vals) / total) * 100

    # Regression-adjusted pay gap — supplementary to pay_gap_by_level
    # above, never replaces it. Imported here (not at module level) to
    # avoid a circular import, since pay_equity_regression imports
    # LEVEL_ORDER from this module.
    from pay_equity_regression import compute_regression_adjusted_pay_gap
    regression_result = compute_regression_adjusted_pay_gap(regression_input_rows)

    return {
        "pay_gap_by_level": pay_gap_by_level,
        "representation_by_level": rep_by_level,
        "promotion": {
            "promotions_a": promoted_a,
            "eligible_a": eligible_a,
            "promotions_b": promoted_b,
            "eligible_b": eligible_b,
            "time_to_promotion_months": {
                "group_a": _average(ttp_a),
                "group_b": _average(ttp_b),
            },
        },
        "regression_adjusted_pay_equity": regression_result,
        "skipped": skipped,
        "total_rows": len(rows),
    }


def aggregate_applicant_rows(rows: List[Dict]) -> Dict:
    """
    rows: list of dicts with keys candidate_id, group, stage_reached.
    stage_reached is the furthest stage that candidate got to. Column
    names are matched flexibly — see csv_columns.py and the note on
    aggregate_employee_rows above. Raises ValueError if a required column
    can't be found under any known spelling.
    """
    rows = remap_rows(rows, kind="applicant")
    counts = {
        "a": {stage: 0 for stage in STAGE_ORDER},
        "b": {stage: 0 for stage in STAGE_ORDER},
    }
    skipped = []

    for i, row in enumerate(rows):
        group = _normalize_group(row.get("group"))
        stage = (row.get("stage_reached") or "").strip().lower()
        if stage not in STAGE_ORDER:
            skipped.append(row.get("candidate_id") or f"row {i + 2}")
            continue
        idx = STAGE_ORDER.index(stage)
        for s in range(idx + 1):
            counts[group][STAGE_ORDER[s]] += 1

    return {
        "hiring_funnel": {
            "funnel_a": counts["a"],
            "funnel_b": counts["b"],
        },
        "skipped": skipped,
        "total_rows": len(rows),
    }
