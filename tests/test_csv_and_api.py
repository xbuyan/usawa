"""
CSV aggregation and API edge-case tests.
"""

import io

from csv_aggregation import aggregate_employee_rows, aggregate_applicant_rows


def test_aggregate_employee_rows_skips_invalid_rows_and_reports_them():
    rows = [
        {"employee_id": "E001", "level": "IC", "group": "a", "salary": "90000",
         "promotion_eligible": "yes", "promoted": "no", "months_to_promotion": ""},
        {"employee_id": "E002", "level": "NotALevel", "group": "b", "salary": "95000",
         "promotion_eligible": "yes", "promoted": "no", "months_to_promotion": ""},
        {"employee_id": "E003", "level": "IC", "group": "b", "salary": "not-a-number",
         "promotion_eligible": "yes", "promoted": "no", "months_to_promotion": ""},
    ]
    result = aggregate_employee_rows(rows)
    assert result["total_rows"] == 3
    assert set(result["skipped"]) == {"E002", "E003"}


def test_aggregate_applicant_rows_cumulative_stage_counting():
    # A candidate who reached "offered" should count in applied, interviewed,
    # AND offered — they passed through all earlier stages to get there.
    rows = [
        {"candidate_id": "C1", "group": "a", "stage_reached": "offered"},
    ]
    result = aggregate_applicant_rows(rows)
    funnel_a = result["hiring_funnel"]["funnel_a"]
    assert funnel_a["applied"] == 1
    assert funnel_a["interviewed"] == 1
    assert funnel_a["offered"] == 1
    assert funnel_a["hired"] == 0


def test_aggregate_applicant_rows_skips_unrecognized_stage():
    rows = [{"candidate_id": "C1", "group": "a", "stage_reached": "ghosted"}]
    result = aggregate_applicant_rows(rows)
    assert result["skipped"] == ["C1"]


def test_score_endpoint_rejects_empty_body(client, registered_user):
    client, email, password = registered_user
    resp = client.post("/api/score", json={})
    assert resp.status_code == 400


def test_score_endpoint_works_with_valid_data(client, registered_user):
    client, email, password = registered_user
    resp = client.post("/api/score", json={
        "pay_gap_by_level": {"IC": 3},
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["overall_score"] is not None


def test_employee_csv_upload_end_to_end(client, registered_user):
    client, email, password = registered_user
    csv_content = (
        "employee_id,level,group,salary,promotion_eligible,promoted,months_to_promotion\n"
        "E001,IC,a,90000,yes,no,\n"
        "E002,IC,b,95000,yes,yes,12\n"
    )
    resp = client.post(
        "/api/parse/employee",
        data={"file": (io.BytesIO(csv_content.encode()), "employees.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "IC" in body["pay_gap_by_level"]


def test_employee_csv_upload_rejects_missing_file(client, registered_user):
    client, email, password = registered_user
    resp = client.post("/api/parse/employee", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
