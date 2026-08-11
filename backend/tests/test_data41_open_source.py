import pytest

from app.chatbi.parser import parse_question
from app.data.open_source import load_manifest
from app.response.composer import ResponseComposer
from app.response.contracts import CompositionRequest, DataEvidence, ResponseProfileName


@pytest.mark.no_db
def test_committed_open_source_snapshots_match_manifest_hashes():
    _, manifest = load_manifest()
    assert manifest["manifest_version"] == "data41-source-manifest-v1"
    assert {row["snapshot_row_count"] for row in manifest["snapshots"]} == {26, 27095}


@pytest.mark.no_db
def test_uci_snapshot_is_explicit_deterministic_sample():
    _, manifest = load_manifest()
    uci = next(row for row in manifest["snapshots"] if row["dataset_code"] == "sales_ops_uci_online_retail")
    assert uci["source_row_count"] == 541909
    assert uci["snapshot_row_count"] == 27095
    assert "Every twentieth" in uci["selection_method"]


@pytest.mark.no_db
def test_chatbi_accepts_explicit_open_source_date_window():
    plan = parse_question("2020年5月9日至2020年6月9日充电收入是多少")
    assert plan.status == "ready"
    assert plan.metrics == ["charging_revenue"]
    assert plan.time_range.start.isoformat() == "2020-05-09"
    assert plan.time_range.end_exclusive.isoformat() == "2020-06-10"


@pytest.mark.no_db
def test_answer_composer_preserves_open_source_truth_label():
    response = ResponseComposer().compose(CompositionRequest(
        question="充电收入是多少",
        profile=ResponseProfileName.EXECUTIVE_BRIEF,
        data_evidence=DataEvidence(
            engine="deterministic",
            scenario_id="charging_ops",
            structured_result={"charging_revenue": 46.12},
            conclusion="充电收入为 46.12 元。",
            data_source="ACN-Data via ORNL",
            run_id="COMPOSITE-DATA41-TEST",
        ),
        trace_id="TRACE-DATA41-TEST",
        run_id="COMPOSITE-DATA41-TEST",
        data_classification="OPEN_SOURCE_DERIVED",
    ))
    assert response.data_classification == "OPEN_SOURCE_DERIVED"
    assert "公开数据样本" in response.warnings[0]
    assert "模拟数据" not in response.warnings[0]


def test_open_source_status_and_schema_catalog_are_authenticated(client, login):
    assert client.get("/api/v1/data/open-source/status").status_code == 401
    headers = login()
    status = client.get("/api/v1/data/open-source/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["status"] == "NOT_READY"
    catalog = client.get("/api/v1/data/open-source/schema-catalog", headers=headers)
    assert catalog.status_code == 200
    body = catalog.json()
    assert body["catalog_version"] == "data41-schema-catalog-v2"
    assert body["sqlbot_enabled"] is False
    assert body["statistics"] == {"table_count": 13, "field_count": 141, "relation_count": 19}
    required = {
        "name", "type", "description", "primary_key", "foreign_key", "relation",
        "business_meaning", "sensitivity", "example_value", "synonym",
    }
    assert all(required <= set(column) for table in body["tables"] for column in table["columns"])
