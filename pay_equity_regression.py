"""
Regression-adjusted pay equity.

The existing pay_equity_score() in dei_scorecard.py compares average pay
within each job level — controlling for level, but nothing else. That's
the meaningfully simpler statistical approach flagged in this project's
own Tier 3 roadmap as the biggest gap versus a "real" pay equity engine
(what Trusaic's engine actually does: control for tenure, performance,
and role scope, not just level).

This module adds that: an OLS regression of salary on level, tenure, and
performance rating, plus a group indicator. The coefficient on the group
indicator is the "unexplained" pay difference — the part that survives
controlling for the legitimate factors above. That's the number that
actually holds up in front of HR/Legal, versus a raw average difference
that might just reflect the group having more tenure or higher average
performance ratings.

Deliberate scope limits, stated up front rather than discovered later:
  - Requires tenure_months and performance_rating columns, which are
    OPTIONAL on CSV upload (see csv_columns.py). Most real customer data
    won't have these on day one. When they're missing, this returns
    usable=False with a specific reason — the simple level-based number
    keeps working regardless, unaffected.
  - "Role scope" (mentioned in the Tier 3 roadmap) is NOT controlled for
    here — there's no clean, honest way to reduce "scope" to a single
    numeric or categorical column without a customer-specific job
    architecture, which is out of scope for a first pass. Level (as an
    ordinal band) is the closest available proxy already in the data.
  - This is ordinary least squares on raw salary, not a more
    sophisticated model (e.g. robust regression, log-salary, mixed
    effects for nested org structure). OLS is the same technique
    real-world pay equity regressions commonly use as a baseline, and is
    the honest, standard place to start.
"""

from typing import Dict, List, Optional

import numpy as np
from scipy import stats

# Deferred import (not at module level): csv_aggregation.py imports this
# module's compute_regression_adjusted_pay_gap, so importing LEVEL_ORDER
# from csv_aggregation at module load time would create a circular import.
# By the time these functions actually run, csv_aggregation is fully
# loaded, so importing inside the function is safe.
def _level_order():
    from csv_aggregation import LEVEL_ORDER
    return LEVEL_ORDER

# Below this many usable rows (after dropping rows missing tenure/
# performance), OLS coefficients and p-values are too noisy to report
# responsibly — small-sample regression coefficients can swing wildly and
# a "significant" result can easily be a sample-size artifact. 30 is a
# conservative, commonly-cited floor for linear regression with several
# predictors (roughly following the "10-20 observations per predictor"
# rule of thumb for a model with ~5-6 parameters here).
MIN_USABLE_N = 30
MIN_PER_GROUP = 5
SIGNIFICANCE_THRESHOLD = 0.05


def _prepare_rows(employee_records: List[Dict]) -> List[Dict]:
    """Keeps only rows with every field the regression needs, all valid."""
    usable = []
    level_order = _level_order()
    for row in employee_records:
        level = row.get("level")
        group = row.get("group")
        salary = row.get("salary")
        tenure = row.get("tenure_months")
        performance = row.get("performance_rating")
        if level not in level_order or group not in ("a", "b"):
            continue
        try:
            salary = float(salary)
            tenure = float(tenure)
            performance = float(performance)
        except (TypeError, ValueError):
            continue
        usable.append({
            "level": level, "group": group, "salary": salary,
            "tenure_months": tenure, "performance_rating": performance,
        })
    return usable


def _build_design_matrix(rows: List[Dict]):
    """
    Returns (X, y, column_names, levels_included).
    X columns: intercept, one dummy per non-reference level actually
    present in the data (reference = the lowest level present, by
    LEVEL_ORDER), tenure_months, performance_rating, is_group_b.
    """
    levels_present = sorted({r["level"] for r in rows}, key=_level_order().index)
    reference_level = levels_present[0]
    level_dummies = levels_present[1:]  # drop reference to avoid the dummy trap

    column_names = ["intercept"] + [f"level_{l}" for l in level_dummies] + \
        ["tenure_months", "performance_rating", "is_group_b"]

    X = np.zeros((len(rows), len(column_names)))
    y = np.zeros(len(rows))

    for i, row in enumerate(rows):
        X[i, 0] = 1.0
        for j, l in enumerate(level_dummies):
            X[i, 1 + j] = 1.0 if row["level"] == l else 0.0
        X[i, -3] = row["tenure_months"]
        X[i, -2] = row["performance_rating"]
        X[i, -1] = 1.0 if row["group"] == "b" else 0.0
        y[i] = row["salary"]

    return X, y, column_names, levels_present


def compute_regression_adjusted_pay_gap(employee_records: List[Dict]) -> Dict:
    """
    employee_records: the same row-level dicts aggregate_employee_rows()
    already has (post column-remapping), each with at least level, group,
    salary, and — for this to be usable — tenure_months and
    performance_rating.

    Always returns a dict with a "usable" boolean. When usable is False,
    "reason" explains exactly why (missing columns, too few rows, no
    variation in group/level, etc.) — the caller should show that reason
    rather than silently omitting the section, per this project's honesty
    standard: absence of a result should never look like "nothing to see
    here" when the real story is "couldn't compute this responsibly."
    """
    usable_rows = _prepare_rows(employee_records)
    n = len(usable_rows)

    if n < MIN_USABLE_N:
        return {
            "usable": False,
            "reason": (
                f"Only {n} rows have both tenure and performance rating filled "
                f"in (need at least {MIN_USABLE_N} for a statistically "
                f"meaningful regression). The level-based pay gap above is "
                f"still valid; this is a supplementary, more rigorous view "
                f"that needs more complete data to run."
            ),
            "usable_n": n,
        }

    group_a_n = sum(1 for r in usable_rows if r["group"] == "a")
    group_b_n = n - group_a_n
    if group_a_n < MIN_PER_GROUP or group_b_n < MIN_PER_GROUP:
        return {
            "usable": False,
            "reason": (
                f"Group A has {group_a_n} usable rows and Group B has "
                f"{group_b_n} — need at least {MIN_PER_GROUP} in each group "
                f"for the comparison to be statistically meaningful."
            ),
            "usable_n": n,
        }

    levels_present = sorted({r["level"] for r in usable_rows}, key=_level_order().index)
    if len(levels_present) < 2 and len({r["tenure_months"] for r in usable_rows}) < 2 \
            and len({r["performance_rating"] for r in usable_rows}) < 2:
        # Degenerate case: every control variable is constant, so there's
        # nothing to control for — the model would just reduce to a
        # simple group-mean comparison, which the level-based score
        # already provides. Rare in real data; guarded rather than
        # assumed impossible.
        return {
            "usable": False,
            "reason": "Not enough variation in level, tenure, or performance "
                       "rating across rows to control for them meaningfully.",
            "usable_n": n,
        }

    X, y, column_names, levels_present = _build_design_matrix(usable_rows)

    k = X.shape[1]  # number of parameters, including intercept
    df = n - k
    if df < 1:
        return {
            "usable": False,
            "reason": f"Too many levels/parameters ({k}) relative to the "
                       f"{n} usable rows to estimate a regression reliably.",
            "usable_n": n,
        }

    rank = np.linalg.matrix_rank(X)
    if rank < k:
        # Perfect collinearity — e.g. every employee at a given level is
        # entirely one group, so level and group can't be told apart
        # statistically. Reported honestly rather than producing
        # meaningless coefficients from a singular matrix.
        return {
            "usable": False,
            "reason": "The data has a pattern (e.g. one group entirely "
                       "concentrated at a specific level) that makes it "
                       "impossible to separate the effect of level from the "
                       "effect of group in this sample.",
            "usable_n": n,
        }

    beta, residuals_sum, rank2, singular_values = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta
    residuals = y - y_hat
    rss = float(np.sum(residuals ** 2))
    tss = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1 - (rss / tss) if tss > 0 else 0.0

    mse = rss / df
    try:
        xtx_inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return {
            "usable": False,
            "reason": "The regression could not be solved numerically for "
                       "this data (a near-singular design matrix).",
            "usable_n": n,
        }
    se_beta = np.sqrt(np.maximum(np.diag(xtx_inv) * mse, 0))

    group_idx = column_names.index("is_group_b")
    group_coefficient = float(beta[group_idx])
    group_se = float(se_beta[group_idx])
    t_stat = group_coefficient / group_se if group_se > 0 else 0.0
    p_value = float(2 * stats.t.sf(abs(t_stat), df))

    avg_salary_a = float(np.mean([r["salary"] for r in usable_rows if r["group"] == "a"]))
    # is_group_b's coefficient is (predicted salary for b) - (predicted
    # salary for a), holding level/tenure/performance constant. Flip the
    # sign and express as a % of group A's average salary, to match the
    # sign convention of the existing simple gap: positive = group A paid
    # more (see pay_equity_score()'s docstring in dei_scorecard.py).
    adjusted_gap_percent = (-group_coefficient / avg_salary_a) * 100 if avg_salary_a else 0.0

    return {
        "usable": True,
        "usable_n": n,
        "group_a_n": group_a_n,
        "group_b_n": group_b_n,
        "controlled_for": ["level", "tenure_months", "performance_rating"],
        "levels_included": levels_present,
        "adjusted_gap_percent": round(adjusted_gap_percent, 2),
        "raw_group_coefficient": round(group_coefficient, 2),
        "p_value": round(p_value, 4),
        "statistically_significant": p_value < SIGNIFICANCE_THRESHOLD,
        "r_squared": round(r_squared, 3),
        "note": (
            "Positive adjusted_gap_percent means Group A is paid more than "
            "Group B after controlling for level, tenure, and performance "
            "rating. statistically_significant is True when p < 0.05 — "
            "below that threshold, the observed gap is more likely to be "
            "random sample noise than a real effect, given this sample size."
        ),
    }
