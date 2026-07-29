import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.bootstrap import MAPPING_FIELDS
from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data
from app.models.auth import AuditLog, User
from app.models.integration import (
    DataIngestionQualityCheck, DataIngestionReview, DataIngestionRun,
    DataSetDefinition, DataSourceConnection, IngestedStationPreview,
    PublishedStationSnapshot, ScenarioPackageRelease,
)
from app.services.data_integration import DataIntegrationError, DataIntegrationService


def test_overview_and_platform_ingestion_are_database_backed(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)
    headers = login()

    overview = client.get(
        "/api/v1/data-integration/overview?start=2026-01-01&end_exclusive=2026-07-01",
        headers=headers,
    )
    assert overview.status_code == 200
    body = overview.json()
    assert {source["source_type"] for source in body["sources"]} == {"postgresql", "mysql", "excel", "api"}
    assert len(body["dataset"]["mapping"]) == 8
    assert len(body["preview"]) == 5
    assert body["metadata"]["source"] == "platform_database"
    assert body["metadata"]["batch_id"].startswith("SIM-")
    assert all(body["validations"].values())

    run = client.post(
        "/api/v1/data-integration/datasets/station-operations/run",
        json={"start": "2026-01-01", "end_exclusive": "2026-07-01", "limit": 5},
        headers=headers,
    )
    assert run.status_code == 200
    assert run.json()["rows_read"] == 5
    assert run.json()["rows_written"] == 5
    assert run.json()["status"] == "completed"
    with SessionLocal() as db:
        assert len(db.scalars(select(IngestedStationPreview)).all()) == 5
        assert db.scalar(select(DataIngestionRun.status)) == "completed"
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "data_ingestion.run"))
        assert audit and "password" not in audit.detail_json.lower()


def test_quality_approval_and_publication_are_database_backed_and_audited(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)
    headers = login()
    run = client.post(
        "/api/v1/data-integration/datasets/station-operations/run",
        json={"start": "2026-01-01", "end_exclusive": "2026-07-01", "limit": 30},
        headers=headers,
    )
    run_id = run.json()["run_id"]

    quality = client.post(
        f"/api/v1/data-integration/datasets/station-operations/runs/{run_id}/quality",
        headers=headers,
    )
    assert quality.status_code == 200
    assert quality.json()["quality_status"] == "passed"
    assert quality.json()["workflow_status"] == "quality_passed"
    assert len(quality.json()["checks"]) == 8

    submitted = client.post(
        f"/api/v1/data-integration/datasets/station-operations/runs/{run_id}/submit",
        headers=headers,
    )
    assert submitted.status_code == 200
    assert submitted.json()["workflow_status"] == "pending_approval"

    approved = client.post(
        f"/api/v1/data-integration/datasets/station-operations/runs/{run_id}/review",
        json={"action": "approve"},
        headers=headers,
    )
    assert approved.status_code == 200
    assert approved.json()["workflow_status"] == "approved"

    published = client.post(
        f"/api/v1/data-integration/datasets/station-operations/runs/{run_id}/publish",
        headers=headers,
    )
    assert published.status_code == 200
    assert published.json()["workflow_status"] == "published"
    assert published.json()["release_version"] == "v1.0"
    assert published.json()["summary"]["snapshot_rows"] == 30

    station_query = client.get(
        "/api/v1/dashboard/stations?start=2026-01-01&end_exclusive=2026-07-01&metrics=charging_revenue,gross_profit&limit=30",
        headers=headers,
    )
    assert station_query.status_code == 200
    assert station_query.json()["metadata"]["query_source"] == "published_station_snapshot"
    assert station_query.json()["metadata"]["dataset_release_version"] == "v1.0"

    overview = client.get(
        "/api/v1/data-integration/overview?start=2026-01-01&end_exclusive=2026-07-01",
        headers=headers,
    ).json()
    assert overview["dataset"]["status"] == "published"
    assert overview["workflow"]["workflow_status"] == "published"
    assert overview["workflow"]["summary"]["rules_passed"] == 8
    with SessionLocal() as db:
        assert len(db.scalars(select(DataIngestionQualityCheck)).all()) == 8
        assert len(db.scalars(select(PublishedStationSnapshot)).all()) == 30
        review = db.scalar(select(DataIngestionReview))
        assert review and review.published_by is not None and review.release_version == "v1.0"
        scenario = db.scalar(select(ScenarioPackageRelease))
        assert scenario and scenario.status == "published" and scenario.source_batch_id.startswith("SIM-")
        actions = set(db.scalars(select(AuditLog.action)).all())
        assert {
            "data_ingestion.quality", "data_ingestion.submit",
            "data_ingestion.review", "data_ingestion.publish",
        }.issubset(actions)

    client.post(
        "/api/v1/data-integration/datasets/station-operations/run",
        json={"start": "2026-01-01", "end_exclusive": "2026-07-01", "limit": 5},
        headers=headers,
    )
    with SessionLocal() as db:
        assert len(db.scalars(select(IngestedStationPreview)).all()) == 5
        assert len(db.scalars(select(PublishedStationSnapshot)).all()) == 30


def test_quality_failure_and_invalid_publication_fail_closed(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)
    headers = login()
    run_id = client.post(
        "/api/v1/data-integration/datasets/station-operations/run",
        json={"start": "2026-01-01", "end_exclusive": "2026-07-01", "limit": 5},
        headers=headers,
    ).json()["run_id"]
    with SessionLocal() as db:
        row = db.scalar(select(IngestedStationPreview).order_by(IngestedStationPreview.id))
        row.charging_revenue = -1
        db.commit()

    quality = client.post(
        f"/api/v1/data-integration/datasets/station-operations/runs/{run_id}/quality",
        headers=headers,
    )
    assert quality.status_code == 200
    assert quality.json()["quality_status"] == "failed"
    assert quality.json()["summary"]["failures"] == ["DQI-005"]
    assert client.post(
        f"/api/v1/data-integration/datasets/station-operations/runs/{run_id}/submit",
        headers=headers,
    ).status_code == 409
    assert client.post(
        f"/api/v1/data-integration/datasets/station-operations/runs/{run_id}/publish",
        headers=headers,
    ).status_code == 409


def test_connection_test_is_audited_and_credentials_are_never_persisted(client, login):
    headers = login()
    response = client.post("/api/v1/data-integration/sources/platform-postgresql/test", json={}, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "passed"
    assert response.json()["credential_persisted"] is False

    missing = client.post("/api/v1/data-integration/sources/chatbi-mysql/test", json={}, headers=headers)
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "CREDENTIAL_REQUIRED"
    with SessionLocal() as db:
        source = db.get(DataSourceConnection, "chatbi-mysql")
        assert source is not None
        assert "password" not in {column.name for column in source.__table__.columns}
        audits = list(db.scalars(select(AuditLog).where(AuditLog.action == "data_source.test")))
        assert len(audits) == 2
        assert all("password" not in item.detail_json.lower() for item in audits)


def test_regional_user_cannot_test_or_run_connectors(client, login):
    headers = login("regional", "AlphaRegion!2026")
    assert client.post("/api/v1/data-integration/sources/platform-postgresql/test", json={}, headers=headers).status_code == 403
    assert client.post(
        "/api/v1/data-integration/datasets/station-operations/run",
        json={"start": "2026-01-01", "end_exclusive": "2026-07-01"},
        headers=headers,
    ).status_code == 403
    assert client.post(
        "/api/v1/data-integration/datasets/station-operations/runs/ING-UNKNOWN/quality",
        headers=headers,
    ).status_code == 403
    assert client.post(
        "/api/v1/data-integration/datasets/station-operations/runs/ING-UNKNOWN/publish",
        headers=headers,
    ).status_code == 403


def test_excel_rows_are_parsed_then_persisted_in_database(client, tmp_path):
    with SessionLocal() as db:
        source = db.get(DataSourceConnection, "excel-import")
        source.resource_locator = "station_operations.xlsx"
        db.add(DataSetDefinition(
            dataset_id="excel-station-test",
            source_id=source.source_id,
            display_name="Excel 场站接入测试",
            source_object="station_operations.xlsx",
            target_table="ingested_station_preview",
            standard_schema="charging_ops",
            mapping_json=json.dumps(MAPPING_FIELDS, ensure_ascii=False),
            data_classification="simulated",
            status="draft",
        ))
        db.commit()

        workbook = Workbook()
        sheet = workbook.active
        sheet.append([item["source"] for item in MAPPING_FIELDS])
        sheet.append(["XL001", "Excel模拟充电站", "R01", "C01", 12680.5, 9320.25, 3260.25, 0.2571])
        workbook.save(tmp_path / source.resource_locator)

        user = db.scalar(select(User).where(User.username == "analyst"))
        service = DataIntegrationService(db, user)
        service.settings.data_import_root = str(tmp_path)
        tested = service.test_source(source.source_id)
        assert tested["status"] == "passed"
        result = service.ingest_dataset(
            "excel-station-test", date(2026, 1, 1), date(2026, 7, 1), limit=10,
        )
        assert result["rows_written"] == 1
        stored = db.scalar(select(IngestedStationPreview).where(IngestedStationPreview.dataset_id == "excel-station-test"))
        assert stored and stored.station_id == "XL001"
        assert str(stored.charging_revenue) == "12680.50"


@pytest.mark.parametrize("file_name,expected_station", [
    ("station_operations_region_a.csv", "FILE-A-001"),
    ("station_operations_region_b.csv", "FILE-B-001"),
])
def test_two_versioned_csv_samples_pass_connector_contract(client, file_name, expected_station):
    sample_root = Path(__file__).parents[2] / "samples" / "data" / "charging_ops"
    with SessionLocal() as db:
        source = db.get(DataSourceConnection, "excel-import")
        source.resource_locator = file_name
        dataset_id = f"csv-{expected_station.lower()}"
        db.add(DataSetDefinition(
            dataset_id=dataset_id, source_id=source.source_id,
            display_name=f"CSV 样例 {expected_station}", source_object=file_name,
            target_table="ingested_station_preview", standard_schema="charging_ops",
            mapping_json=json.dumps(MAPPING_FIELDS, ensure_ascii=False),
            data_classification="simulated", status="draft",
        ))
        db.commit()
        user = db.scalar(select(User).where(User.username == "analyst"))
        service = DataIntegrationService(db, user)
        service.settings.data_import_root = str(sample_root)
        assert service.test_source(source.source_id)["details"]["row_count"] == 2
        result = service.ingest_dataset(dataset_id, date(2026, 1, 1), date(2026, 7, 1), limit=10)
        assert result["rows_written"] == 2
        stored = db.scalar(select(IngestedStationPreview).where(
            IngestedStationPreview.dataset_id == dataset_id,
            IngestedStationPreview.station_id == expected_station,
        ))
        assert stored and stored.data_classification == "simulated"


class _ApiHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"rows": [{
            "station_id": "API001", "station_name": "API模拟充电站", "region_id": "R02", "city_id": "C03",
            "charging_revenue": 8888.8, "charging_volume_kwh": 6666.6,
            "gross_profit": 2222.2, "gross_margin": 0.25,
        }]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        return


def test_api_rows_are_fetched_then_persisted_in_database(client):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with SessionLocal() as db:
            source = db.get(DataSourceConnection, "api-import")
            source.resource_locator = f"http://127.0.0.1:{server.server_port}/station-operations"
            db.add(DataSetDefinition(
                dataset_id="api-station-test",
                source_id=source.source_id,
                display_name="API 场站接入测试",
                source_object="station-operations",
                target_table="ingested_station_preview",
                standard_schema="charging_ops",
                mapping_json=json.dumps(MAPPING_FIELDS, ensure_ascii=False),
                data_classification="simulated",
                status="draft",
            ))
            db.commit()
            user = db.scalar(select(User).where(User.username == "analyst"))
            service = DataIntegrationService(db, user)
            assert service.test_source(source.source_id)["status"] == "passed"
            result = service.ingest_dataset(
                "api-station-test", date(2026, 1, 1), date(2026, 7, 1), limit=10,
            )
            assert result["rows_written"] == 1
            stored = db.scalar(select(IngestedStationPreview).where(IngestedStationPreview.dataset_id == "api-station-test"))
            assert stored and stored.station_id == "API001"
    finally:
        server.shutdown()
        server.server_close()


def test_unsafe_paths_and_api_hosts_fail_closed(client, tmp_path):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "analyst"))
        service = DataIntegrationService(db, user)
        service.settings.data_import_root = str(tmp_path)
        excel = db.get(DataSourceConnection, "excel-import")
        try:
            service.test_source(excel.source_id, resource_locator="../outside.xlsx")
        except DataIntegrationError as exc:
            assert exc.code == "UNSAFE_FILE_PATH"
        else:
            raise AssertionError("unsafe path should be rejected")

        api = db.get(DataSourceConnection, "api-import")
        try:
            service.test_source(api.source_id, resource_locator="https://example.com/data")
        except DataIntegrationError as exc:
            assert exc.code == "API_HOST_NOT_ALLOWED"
        else:
            raise AssertionError("unallowlisted API host should be rejected")
