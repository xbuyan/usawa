"""
Scoring engine tests — these matter more than most, since the whole product's
credibility rests on this math being right. Covers the four-fifths rule
implementation directly against known reference points.
"""

from dei_scorecard import (
    calculate_scorecard,
    _four_fifths_score,
    pay_equity_score,
    promotion_equity_score,
    hiring_funnel_score,
)


def test_four_fifths_rule_exact_boundary():
    # Exactly 0.8 ratio should pass the rule (>= 0.8, not > 0.8).
    result = _four_fifths_score(rate_a=0.8, rate_b=1.0)
    assert result["passes_four_fifths_rule"] is True
    assert result["ratio"] == 0.8


def test_four_fifths_rule_just_below_boundary_fails():
    result = _four_fifths_score(rate_a=0.79, rate_b=1.0)
    assert result["passes_four_fifths_rule"] is False


def test_four_fifths_rule_equal_rates_scores_perfect():
    result = _four_fifths_score(rate_a=0.5, rate_b=0.5)
    assert result["ratio"] == 1.0
    assert result["score"] == 100


def test_four_fifths_rule_order_independent():
    # The rule compares the lower rate to the higher rate — which group is
    # "a" vs "b" shouldn't change the outcome.
    r1 = _four_fifths_score(rate_a=0.2, rate_b=0.5)
    r2 = _four_fifths_score(rate_a=0.5, rate_b=0.2)
    assert r1["ratio"] == r2["ratio"]


def test_promotion_equity_known_reference_case():
    # Reference case verified during development: 8/60 vs 15/65 promotion
    # rates -> 13.3% vs 23.1% -> ratio ~0.578 -> fails four-fifths rule.
    result = promotion_equity_score(
        promotions_a=8, eligible_a=60,
        promotions_b=15, eligible_b=65,
    )
    assert result["passes_four_fifths_rule"] is False
    assert 0.55 < result["four_fifths_ratio"] < 0.60


def test_pay_equity_score_zero_gap_is_perfect():
    result = pay_equity_score({"IC": 0})
    assert result["score"] == 100


def test_pay_equity_score_large_gap_scores_low():
    result = pay_equity_score({"IC": 20})
    assert result["score"] <= 15


def test_hiring_funnel_score_driven_by_worst_stage():
    # One bad stage should drag the whole funnel score down even if other
    # stages look fine — a company can't hide a bad stage in an average.
    result = hiring_funnel_score(
        funnel_a={"applied": 100, "interviewed": 50, "offered": 5, "hired": 5},
        funnel_b={"applied": 100, "interviewed": 50, "offered": 40, "hired": 40},
    )
    assert result["passes_four_fifths_rule"] is False
    assert result["worst_stage"] == "interviewed_to_offered"


def test_calculate_scorecard_handles_partial_data():
    # A client might only have pay data at first — the tool shouldn't crash,
    # and should redistribute weights across whatever sections are present.
    result = calculate_scorecard({"pay_gap_by_level": {"IC": 3}})
    assert result["overall_score"] is not None
    assert "pay_equity" in result["sub_scores"]
    assert "promotion_equity" not in result["sub_scores"]


def test_calculate_scorecard_empty_input_returns_none_score():
    result = calculate_scorecard({})
    assert result["overall_score"] is None
    assert result["sub_scores"] == {}
