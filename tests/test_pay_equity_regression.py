"""
Regression-adjusted pay equity tests.

The core test (test_recovers_known_true_group_effect) is the important
one: it builds synthetic data where salary is generated from a KNOWN
formula (level effect + tenure effect + performance effect + a specific
group effect + small noise), then checks the regression recovers that
known group effect. This verifies the math is actually correct — not
just that the code runs without an exception on some data.
"""

import numpy as np
import pytest

from pay_equity_regression import compute_regression_adjusted_pay_gap
from csv_aggregation import aggregate_employee_rows

LEVELS = ["IC", "Manager", "Director"]
LEVEL_EFFECT = {"IC": 0, "Manager": 20000, "Director": 40000}
TRUE_GROUP_B_EFFECT = -3000  # group B paid 3000 less, holding everything else equal
TENURE_COEF = 100  # $ per month of tenure
PERFORMANCE_COEF = 2000  # $ per rating point
BASE_SALARY = 60000


def _make_synthetic_rows(n_per_cell=6, noise_std=150, seed=42):
    """
    Builds a full grid: every (level, group) combination gets n_per_cell
    rows with varying tenure and performance, so level/tenure/performance/
    group all vary independently (no collinearity) and salary is computed
    EXACTLY from the known formula plus small random noise.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for level in LEVELS:
        for group in ("a", "b"):
            for i in range(n_per_cell):
                tenure = 6 + i * 7  # 6, 13, 20, ... varies within each cell
                performance = 2 + (i % 4)  # cycles 2,3,4,5
                true_salary = (
                    BASE_SALARY + LEVEL_EFFECT[level]
                    + TENURE_COEF * tenure
                    + PERFORMANCE_COEF * performance
                    + (TRUE_GROUP_B_EFFECT if group == "b" else 0)
                    + rng.normal(0, noise_std)
                )
                rows.append({
                    "level": level, "group": group, "salary": true_salary,
                    "tenure_months": tenure, "performance_rating": performance,
                })
    return rows


def test_recovers_known_true_group_effect():
    rows = _make_synthetic_rows()
    result = compute_regression_adjusted_pay_gap(rows)

    assert result["usable"] is True
    assert result["usable_n"] == len(rows)
    # With real (if small) noise, OLS won't recover the true coefficient
    # exactly, but should get close — well within a few multiples of the
    # noise scale. This proves the math is right, not just plausible.
    assert abs(result["raw_group_coefficient"] - TRUE_GROUP_B_EFFECT) < 300
    assert result["r_squared"] > 0.98  # noise is small relative to effect sizes
    # A real, consistent effect of this size across 36 rows should come
    # through as statistically significant.
    assert result["statistically_significant"] is True
    assert result["p_value"] < 0.05
    # Sign convention check: group B is paid LESS in the synthetic data,
    # so group A should show as paid MORE (positive adjusted_gap_percent).
    assert result["adjusted_gap_percent"] > 0


def test_no_true_group_effect_is_not_flagged_significant():
    # Same generator, but with the group effect set to zero — the
    # regression should NOT report a significant gap when there isn't one.
    rng_rows = _make_synthetic_rows()
    for r in rng_rows:
        # Strip out the group effect that _make_synthetic_rows baked in
        # for group b, by rebuilding salaries without it.
        pass
    # Simplest correct approach: regenerate with TRUE_GROUP_B_EFFECT = 0
    # inline, rather than trying to reverse-engineer the above.
    rng = np.random.default_rng(7)
    rows = []
    for level in LEVELS:
        for group in ("a", "b"):
            for i in range(6):
                tenure = 6 + i * 7
                performance = 2 + (i % 4)
                salary = (
                    BASE_SALARY + LEVEL_EFFECT[level]
                    + TENURE_COEF * tenure + PERFORMANCE_COEF * performance
                    + rng.normal(0, 150)
                )
                rows.append({
                    "level": level, "group": group, "salary": salary,
                    "tenure_months": tenure, "performance_rating": performance,
                })
    result = compute_regression_adjusted_pay_gap(rows)
    assert result["usable"] is True
    assert result["statistically_significant"] is False
    assert abs(result["adjusted_gap_percent"]) < 3  # should be near zero


def test_insufficient_sample_size_is_reported_honestly():
    rows = _make_synthetic_rows(n_per_cell=2)  # only 12 rows total, below MIN_USABLE_N
    result = compute_regression_adjusted_pay_gap(rows)
    assert result["usable"] is False
    assert "30" in result["reason"] or "least" in result["reason"].lower()


def test_missing_tenure_and_performance_columns_reported_honestly():
    # Rows with only the fields the simple comparison needs — the
    # regression should gracefully say "not enough data," never crash or
    # silently fabricate a number.
    rows = [
        {"level": "IC", "group": "a", "salary": 90000},
        {"level": "IC", "group": "b", "salary": 88000},
    ]
    result = compute_regression_adjusted_pay_gap(rows)
    assert result["usable"] is False
    assert result["usable_n"] == 0


def test_too_few_rows_in_one_group_is_reported_honestly():
    rows = _make_synthetic_rows(n_per_cell=10)
    # Remove all but 2 group-b rows to force the per-group floor to fail.
    group_a = [r for r in rows if r["group"] == "a"]
    group_b = [r for r in rows if r["group"] == "b"][:2]
    result = compute_regression_adjusted_pay_gap(group_a + group_b)
    assert result["usable"] is False
    assert "Group B" in result["reason"]


def test_perfect_collinearity_between_level_and_group_is_caught():
    # Every Manager is group b, every IC is group a — level and group are
    # then perfectly correlated, so the model can't separate their
    # effects. Must be caught, not silently produce garbage coefficients.
    rows = []
    rng = np.random.default_rng(1)
    for i in range(20):
        rows.append({
            "level": "IC", "group": "a", "salary": 80000 + rng.normal(0, 100),
            "tenure_months": 10 + i, "performance_rating": 3 + (i % 3),
        })
        rows.append({
            "level": "Manager", "group": "b", "salary": 100000 + rng.normal(0, 100),
            "tenure_months": 10 + i, "performance_rating": 3 + (i % 3),
        })
    result = compute_regression_adjusted_pay_gap(rows)
    assert result["usable"] is False


def test_aggregate_employee_rows_includes_regression_when_data_present():
    rows = []
    for r in _make_synthetic_rows():
        rows.append({
            "employee_id": "E1", "level": r["level"], "group": r["group"],
            "salary": str(r["salary"]), "tenure_months": str(r["tenure_months"]),
            "performance_rating": str(r["performance_rating"]),
            "promotion_eligible": "no", "promoted": "no", "months_to_promotion": "",
        })
    result = aggregate_employee_rows(rows)
    assert "regression_adjusted_pay_equity" in result
    assert result["regression_adjusted_pay_equity"]["usable"] is True
    # The simple level-based gap must still be present and computed as
    # before — the regression is additive, never a replacement.
    assert result["pay_gap_by_level"]


def test_aggregate_employee_rows_without_optional_columns_still_works():
    # Confirms the regression addition doesn't break the existing,
    # already-tested behavior when tenure/performance simply aren't in
    # the CSV at all — the bread-and-butter case for most real uploads.
    rows = [
        {"employee_id": "E001", "level": "IC", "group": "a", "salary": "90000",
         "promotion_eligible": "yes", "promoted": "no", "months_to_promotion": ""},
    ]
    result = aggregate_employee_rows(rows)
    assert result["total_rows"] == 1
    assert result["skipped"] == []
    assert result["regression_adjusted_pay_equity"]["usable"] is False


def test_tenure_years_column_is_converted_to_months():
    # Provides tenure in YEARS under a real-world header spelling, with
    # no tenure_months column at all — confirms the year->month conversion
    # in aggregate_employee_rows actually runs (indirectly: if it didn't,
    # every row would be missing tenure_months and the regression would
    # report usable=False for lack of data).
    rows = []
    rng_rows = _make_synthetic_rows()
    for r in rng_rows:
        rows.append({
            "employee_id": "E1", "level": r["level"], "group": r["group"],
            "salary": str(r["salary"]),
            "Tenure (Years)": str(r["tenure_months"] / 12),
            "performance_rating": str(r["performance_rating"]),
            "promotion_eligible": "no", "promoted": "no", "months_to_promotion": "",
        })
    result = aggregate_employee_rows(rows)
    assert result["regression_adjusted_pay_equity"]["usable"] is True


def test_score_endpoint_passes_through_regression_data_without_changing_score(client, registered_user):
    client, email, password = registered_user
    rows = _make_synthetic_rows()
    payload_rows = [{
        "level": r["level"], "group": r["group"], "salary": r["salary"],
        "tenure_months": r["tenure_months"], "performance_rating": r["performance_rating"],
    } for r in rows]
    regression_result = compute_regression_adjusted_pay_gap(payload_rows)

    pay_gap_by_level = {"IC": 3.0, "Manager": 8.0}

    resp_without = client.post("/api/score", json={"pay_gap_by_level": pay_gap_by_level})
    resp_with = client.post("/api/score", json={
        "pay_gap_by_level": pay_gap_by_level,
        "regression_adjusted_pay_equity": regression_result,
    })

    assert resp_without.status_code == 200
    assert resp_with.status_code == 200
    body_without = resp_without.get_json()
    body_with = resp_with.get_json()

    # Adding regression data must not change the score at all.
    assert body_without["overall_score"] == body_with["overall_score"]
    assert body_without["sub_scores"] == body_with["sub_scores"]
    # But it should show up, clearly labeled, in the details.
    assert "regression_adjusted_pay_equity" not in body_without["details"]
    assert body_with["details"]["regression_adjusted_pay_equity"]["usable"] is True
