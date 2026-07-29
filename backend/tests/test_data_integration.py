import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from openpyxl import Workbook
from sqlalchemy import select

from app.bootstrap import MAPPING_FIELDS
from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data
from app.models.auth import AuditLog, User
from app.models.integration import (
    DataIngestionRun, DataSetDefinition, DataSourceConnection, IngestedStationPreview,
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
