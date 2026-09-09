"""
Flexible CSV column mapping.

Previously, CSV uploads required exact template column names — a real
customer's HR export (e.g. "Employee ID", "Job Level", "Base Salary")
would not match "employee_id", "level", "salary" and every row would
silently get skipped, with no clear error pointing at why. This module
maps a broad set of common real-world header spellings onto the
canonical field names aggregate_employee_rows/aggregate_applicant_rows
expect, and raises a clear, actionable error when a REQUIRED column
genuinely can't be found under any known spelling — rather than quietly
processing zero usable rows.

Design choice: this is a synonym allowlist, not fuzzy/similarity matching.
Fuzzy matching on HR data (salary/demographic columns) risks silently
mapping the wrong column together, which would produce a confidently
wrong equity score — worse than a loud, honest "we couldn't find this
column" error. If a real customer's header isn't covered here, that's
tracked explicitly (see README's "what's still missing") rather than
guessed at.
"""

import re
from typing import Dict, List, Optional, Set, Tuple


def _normalize_header(h: str) -> str:
    """'Employee ID', 'employee-id', ' Employee_ID ' all become 'employee_id'."""
    h = (h or "").strip().lower()
    h = re.sub(r"[\s\-]+", "_", h)
    h = re.sub(r"_+", "_", h)
    return h.strip("_")


# canonical_name -> set of normalized header spellings that mean it.
# The canonical name itself is always included implicitly.
EMPLOYEE_COLUMN_SYNONYMS: Dict[str, Set[str]] = {
    "employee_id": {"employee_id", "emp_id", "id", "staff_id", "employee_number", "emp_no"},
    "level": {"level", "job_level", "band", "grade", "seniority", "job_band", "career_level"},
    "group": {"group", "demographic_group", "category", "protected_group", "gender_group", "comparison_group"},
    "salary": {"salary", "pay", "compensation", "base_salary", "annual_salary", "base_pay", "total_compensation"},
    "promotion_eligible": {"promotion_eligible", "eligible_for_promotion", "promo_eligible", "promotion_eligibility"},
    "promoted": {"promoted", "was_promoted", "got_promoted", "promotion_status"},
    "months_to_promotion": {"months_to_promotion", "time_to_promotion", "ttp_months", "months_since_eligible"},
}

APPLICANT_COLUMN_SYNONYMS: Dict[str, Set[str]] = {
    "candidate_id": {"candidate_id", "applicant_id", "id", "candidate_number"},
    "group": {"group", "demographic_group", "category", "protected_group", "gender_group", "comparison_group"},
    "stage_reached": {"stage_reached", "stage", "furthest_stage", "application_stage", "current_stage", "final_stage"},
}

EMPLOYEE_REQUIRED = {"level", "group", "salary"}
APPLICANT_REQUIRED = {"group", "stage_reached"}


def _build_header_map(
    fieldnames: List[str], synonyms: Dict[str, Set[str]], required: Set[str]
) -> Tuple[Dict[str, str], List[str]]:
    """
    Returns (header_to_canonical, missing_required_canonicals).
    header_to_canonical maps each ORIGINAL header string to the canonical
    field name it was matched to (only for headers that matched something).
    """
    normalized_to_original = {_normalize_header(h): h for h in fieldnames}
    header_to_canonical: Dict[str, str] = {}
    found_canonicals: Set[str] = set()

    for canonical, aliases in synonyms.items():
        all_aliases = aliases | {canonical}
        for normalized_header, original_header in normalized_to_original.items():
            if normalized_header in all_aliases:
                header_to_canonical[original_header] = canonical
                found_canonicals.add(canonical)
                break  # first matching header wins if there were duplicates

    missing = sorted(required - found_canonicals)
    return header_to_canonical, missing


def remap_rows(rows: List[Dict], kind: str) -> List[Dict]:
    """
    kind: 'employee' or 'applicant'.

    Rewrites each row's keys from whatever headers the CSV actually used
    to the canonical names the aggregation functions expect. Raises
    ValueError with a clear, actionable message if a required column
    can't be found under any known spelling — this is meant to be caught
    by the route and returned as a clean 400, the same pattern already
    used for oversized files.
    """
    if not rows:
        return rows

    synonyms = EMPLOYEE_COLUMN_SYNONYMS if kind == "employee" else APPLICANT_COLUMN_SYNONYMS
    required = EMPLOYEE_REQUIRED if kind == "employee" else APPLICANT_REQUIRED
    # Union of keys across all rows — DictReader normally gives every row
    # identical keys, but this is robust even if some rows have missing
    # trailing columns (a real thing that happens with ragged CSVs).
    all_headers: Set[str] = set()
    for row in rows:
        all_headers.update(row.keys())

    header_to_canonical, missing = _build_header_map(sorted(all_headers), synonyms, required)

    if missing:
        seen = ", ".join(sorted(all_headers)) or "(no columns detected)"
        needed = ", ".join(missing)
        raise ValueError(
            f"Couldn't find the required column(s): {needed}. "
            f"Columns found in your file: {seen}. "
            f"Rename the relevant column(s) to match, or contact us if your "
            f"export uses a header name we don't recognize yet."
        )

    remapped = []
    for row in rows:
        new_row = dict(row)  # preserve any unmapped extra columns, unharmed
        for original_header, canonical in header_to_canonical.items():
            if original_header in row:
                new_row[canonical] = row[original_header]
        remapped.append(new_row)
    return remapped
