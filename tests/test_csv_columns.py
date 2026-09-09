"""
Flexible CSV column mapping tests. Confirms:
- exact template column names still work exactly as before (no regression)
- common real-world header spellings are correctly recognized
- a genuinely unrecognized required column produces a clear, actionable
  error instead of silently skipping every row
"""

import pytest

from csv_aggregation import aggregate_employee_rows, aggregate_applicant_rows
from csv_columns import remap_rows


def test_exact_template_headers_still_work_unchanged():
    # Regression check: the original hardcoded column names must keep
    # working exactly as they did before this change.
    rows = [
        {"employee_id": "E001", "level": "IC", "group": "a", "salary": "90000",
         "promotion_eligible": "yes", "promoted": "no", "months_to_promotion": ""},
    ]
    result = aggregate_employee_rows(rows)
    assert result["total_rows"] == 1
    assert result["skipped"] == []


def test_real_world_employee_header_spellings_are_recognized():
    rows = [
        {"Employee ID": "E001", "Job Level": "IC", "Group": "a", "Base Salary": "90000",
         "Eligible For Promotion": "yes", "Was Promoted": "no", "Time To Promotion": ""},
        {"Employee ID": "E002", "Job Level": "IC", "Group": "b", "Base Salary": "80000",
         "Eligible For Promotion": "no", "Was Promoted": "no", "Time To Promotion": ""},
    ]
    result = aggregate_employee_rows(rows)
    assert result["total_rows"] == 2
    assert result["skipped"] == []  # both rows should be usable, not silently dropped
    assert result["pay_gap_by_level"]  # actually produced real aggregated output


def test_real_world_applicant_header_spellings_are_recognized():
    rows = [
        {"Applicant ID": "C1", "Group": "a", "Current Stage": "offered"},
    ]
    result = aggregate_applicant_rows(rows)
    assert result["skipped"] == []
    assert result["hiring_funnel"]["funnel_a"]["offered"] == 1


def test_missing_required_column_raises_clear_error_not_silent_skip():
    # "salary" is missing entirely — no synonym present anywhere in the
    # header. Should fail loudly and specifically, not just skip every row.
    rows = [
        {"employee_id": "E001", "level": "IC", "group": "a"},
    ]
    with pytest.raises(ValueError) as exc_info:
        aggregate_employee_rows(rows)
    message = str(exc_info.value)
    assert "salary" in message.lower()


def test_missing_required_applicant_column_raises_clear_error():
    rows = [{"candidate_id": "C1", "group": "a"}]  # no stage column at all
    with pytest.raises(ValueError) as exc_info:
        aggregate_applicant_rows(rows)
    assert "stage" in str(exc_info.value).lower()


def test_case_and_punctuation_insensitive_matching():
    rows = [
        {"employee-id": "E1", "Level": "IC", "GROUP": "a", "Salary": "90000"},
    ]
    result = aggregate_employee_rows(rows)
    assert result["skipped"] == []


def test_empty_rows_list_is_a_noop():
    # No rows at all — remap_rows should not error just because there's
    # nothing to check headers against (app.py separately rejects an
    # entirely empty upload before this is reached).
    assert remap_rows([], kind="employee") == []
