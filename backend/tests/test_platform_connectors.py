import os
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.platform.connectors import connector_registry
from app.platform.connectors.capabilities import IncrementalMode
from app.platform.connectors.contracts import CancellationToken, ConnectorConfig, PageRequest, Selection
from app.platform.connectors.errors import ConnectorError, ConnectorErrorCode, map_driver_error
from app.platform.connectors.security import StaticCredentialProvider, safe_config


pytestmark = pytest.mark.no_db


def csv_config(root: Path, **overrides) -> ConnectorConfig:
    options = {
        "root_dir": str(root),
        "resource_locator": "sample.csv",
        "data_classification": "simulated",
        **overrides,
    }
    return ConnectorConfig("csv-test", "csv", options)


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    path = tmp_path / "sample.csv"
    path.write_text("id,name,amount\n1,Alpha,12.5\n2,Beta,\n3,Gamma,7\n", encoding="utf-8")
    return path


@pytest.fixture
def sample_excel(tmp_path: Path) -> Path:
    path = tmp_path / "sample.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "records"
    sheet.append(["id", "name", "active"])
    sheet.append([1, "Alpha", True])
    sheet.append([2, "Beta", False])
    second = workbook.create_sheet("empty")
    second.append(["id"])
    workbook.save(path)
    workbook.close()
    return path


def test_registry_and_capability_contract() -> None:
    assert connector_registry.registered_types() == ("csv", "excel", "mock", "mysql", "postgresql")
    connector = connector_registry.create(ConnectorConfig(
        "mock-1", "mock", {"rows": [{"id": 1, "name": "A"}]},
    ))
    assert connector.capabilities.pagination is True
    assert IncrementalMode.WATERMARK in connector.capabilities.incremental_modes
    assert connector.test_connection().server == {"driver": "mock"}


def test_registry_rejects_unknown_type() -> None:
    with pytest.raises(ConnectorError) as exc:
        connector_registry.create(ConnectorConfig("unknown", "unknown", {}))
    assert exc.value.code == ConnectorErrorCode.UNSUPPORTED


def test_plaintext_credential_is_rejected_before_driver_use() -> None:
    with pytest.raises(ConnectorError) as exc:
        connector_registry.create(ConnectorConfig(
            "pg", "postgresql",
            {"host": "db", "database": "sample", "user": "reader", "password": "forbidden"},
            "env://TEST_DB_PASSWORD",
        ))
    assert exc.value.code == ConnectorErrorCode.POLICY_DENIED
    assert "forbidden" not in exc.value.message


def test_safe_config_never_returns_credential_reference_or_value() -> None:
    config = ConnectorConfig(
        "pg", "postgresql",
        {"host": "db", "database": "sample", "user": "reader"},
        "env://TEST_DB_PASSWORD",
    )
    payload = safe_config(config)
    assert payload["credential_configured"] is True
    assert "credential_ref" not in payload
    assert "TEST_DB_PASSWORD" not in str(payload)


def test_csv_discovery_preview_profile_and_pagination(sample_csv: Path) -> None:
    connector = connector_registry.create(csv_config(sample_csv.parent))
    assert [table.name for table in connector.discover_tables()] == ["sample"]
    columns = connector.discover_columns(Selection(table="sample"))
    assert [column.name for column in columns] == ["id", "name", "amount"]
    first = connector.preview_data(Selection(table="sample"), PageRequest(limit=2))
    assert first.row_count == 2
    assert first.next_offset == 2
    assert first.data_classification == "simulated"
    assert first.schema_fingerprint and first.checksum and first.run_id.startswith("CONN-")
    second = connector.read_batch(Selection(table="sample"), PageRequest(limit=2, offset=2))
    assert [row["name"] for row in second.rows] == ["Gamma"]
    assert second.next_offset is None
    profile = connector.profile_data(Selection(table="sample"), PageRequest(limit=3))
    assert profile.row_count == 3
    assert profile.null_counts["amount"] == 1


def test_csv_empty_or_invalid_data_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "sample.csv").write_text("", encoding="utf-8")
    connector = connector_registry.create(csv_config(tmp_path))
    with pytest.raises(ConnectorError) as exc:
        connector.preview_data(Selection(table="sample"))
    assert exc.value.code == ConnectorErrorCode.DATA_ERROR


def test_csv_path_escape_is_denied(tmp_path: Path) -> None:
    with pytest.raises(ConnectorError) as exc:
        connector_registry.create(csv_config(tmp_path, resource_locator="../outside.csv"))
    assert exc.value.code == ConnectorErrorCode.POLICY_DENIED


def test_file_incremental_read_is_explicitly_unsupported(sample_csv: Path) -> None:
    connector = connector_registry.create(csv_config(sample_csv.parent))
    with pytest.raises(ConnectorError) as exc:
        connector.read_incremental(Selection(table="sample", watermark_column="id"), "1")
    assert exc.value.code == ConnectorErrorCode.UNSUPPORTED


def test_cancellation_and_lifecycle_are_enforced(sample_csv: Path) -> None:
    connector = connector_registry.create(csv_config(sample_csv.parent))
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ConnectorError) as exc:
        connector.preview_data(Selection(table="sample"), cancellation=token)
    assert exc.value.code == ConnectorErrorCode.CANCELLED
    connector.close()
    assert connector.health_check().error_code == ConnectorErrorCode.SOURCE_UNAVAILABLE.value


def test_excel_discovery_and_preview(sample_excel: Path) -> None:
    connector = connector_registry.create(ConnectorConfig(
        "excel-test",
        "excel",
        {
            "root_dir": str(sample_excel.parent),
            "resource_locator": sample_excel.name,
            "data_classification": "simulated",
        },
    ))
    assert [table.name for table in connector.discover_tables()] == ["records", "empty"]
    batch = connector.preview_data(Selection(table="records"), PageRequest(limit=10))
    assert batch.row_count == 2
    assert batch.rows[0]["active"] is True
    assert [column.normalized_type for column in batch.columns] == ["integer", "string", "boolean"]


def test_excel_missing_sheet_fails_without_fallback(sample_excel: Path) -> None:
    connector = connector_registry.create(ConnectorConfig(
        "excel-test", "excel",
        {"root_dir": str(sample_excel.parent), "resource_locator": sample_excel.name},
    ))
    with pytest.raises(ConnectorError) as exc:
        connector.preview_data(Selection(table="missing"))
    assert exc.value.code == ConnectorErrorCode.DATA_ERROR


def test_mock_incremental_cursor_and_failure_mapping() -> None:
    connector = connector_registry.create(ConnectorConfig(
        "mock-1", "mock",
        {"rows": [{"id": 1}, {"id": 2}, {"id": 3}]},
    ))
    batch = connector.read_incremental(Selection(table="records", watermark_column="id"), "1", PageRequest(limit=1))
    assert batch.row_count == 1
    assert batch.rows[0]["id"] == 2
    assert batch.cursor == "2"

    failing = connector_registry.create(ConnectorConfig(
        "mock-fail", "mock", {"failure": "TIMEOUT"},
    ))
    with pytest.raises(ConnectorError) as exc:
        failing.preview_data(Selection(table="records"))
    assert exc.value.code == ConnectorErrorCode.TIMEOUT
    assert exc.value.retryable is False


def test_driver_error_mapping_is_stable_and_redacted() -> None:
    assert map_driver_error(TimeoutError("driver timeout with internal details")).code == ConnectorErrorCode.TIMEOUT
    mapped = map_driver_error(RuntimeError("authentication failed for sensitive input"))
    assert mapped.code == ConnectorErrorCode.CREDENTIAL_ERROR
    assert "sensitive" not in mapped.message


def test_mysql_registration_configuration_and_connection_contract(monkeypatch) -> None:
    config = ConnectorConfig(
        "mysql-test",
        "mysql",
        {"host": "db", "database": "sample", "user": "reader"},
        "env://TEST_MYSQL_PASSWORD",
    )
    provider = StaticCredentialProvider({"env://TEST_MYSQL_PASSWORD": "test-only-value"})
    connector = connector_registry.create(config, provider)
    assert connector.capabilities.batch is True
    assert connector.capabilities.incremental_modes == (IncrementalMode.NONE,)

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, *_):
            return None

        def fetchone(self):
            return {"version": "test", "user": "reader", "database": "sample"}

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def rollback(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr("app.platform.connectors.mysql.pymysql.connect", lambda **_: FakeConnection())
    result = connector.test_connection()
    assert result.status == "ok"
    assert "test-only-value" not in str(result)


def test_postgresql_configuration_requires_reference() -> None:
    with pytest.raises(ConnectorError) as exc:
        connector_registry.create(ConnectorConfig(
            "pg-test", "postgresql",
            {"host": "db", "database": "sample", "user": "reader"},
        ))
    assert exc.value.code == ConnectorErrorCode.CREDENTIAL_ERROR


def test_postgresql_schema_and_column_discovery(monkeypatch) -> None:
    connector = connector_registry.create(
        ConnectorConfig(
            "pg-test",
            "postgresql",
            {
                "host": "db",
                "database": "sample",
                "user": "reader",
                "allowed_schemas": ["analytics"],
            },
            "env://TEST_DB_PASSWORD",
        ),
        StaticCredentialProvider({"env://TEST_DB_PASSWORD": "test-only-value"}),
    )

    class FakeCursor:
        result = []

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, query, params=None):
            query_text = str(query)
            if "information_schema.schemata" in query_text:
                self.result = [("analytics",)]
            elif "information_schema.columns" in query_text:
                assert params == ("analytics", "records")
                self.result = [
                    ("id", "bigint", "NO", 1),
                    ("amount", "numeric", "YES", 2),
                ]
            elif "pg_catalog.pg_constraint" in query_text:
                assert params == ("analytics", "records")
                self.result = [
                    ("records_parent_id_fkey", "parent_id", "parents", "id"),
                ]

        def fetchall(self):
            return self.result

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(connector, "_connect", lambda *_: FakeConnection())
    assert connector.discover_schemas() == (connector.discover_schemas()[0],)
    columns = connector.discover_columns(Selection(schema="analytics", table="records"))
    assert [(column.name, column.normalized_type) for column in columns] == [
        ("id", "integer"),
        ("amount", "number"),
    ]
    relationships = connector.discover_relationships(
        Selection(schema="analytics", table="records")
    )
    assert relationships[0].target_table == "parents"


def test_postgresql_schema_allowlist_is_fail_closed() -> None:
    connector = connector_registry.create(
        ConnectorConfig(
            "pg-test",
            "postgresql",
            {
                "host": "db",
                "database": "sample",
                "user": "reader",
                "allowed_schemas": ["analytics"],
            },
            "env://TEST_DB_PASSWORD",
        ),
        StaticCredentialProvider({"env://TEST_DB_PASSWORD": "test-only-value"}),
    )
    with pytest.raises(ConnectorError) as exc:
        connector.discover_tables("private")
    assert exc.value.code == ConnectorErrorCode.POLICY_DENIED


def test_page_request_hard_limits() -> None:
    with pytest.raises(ConnectorError) as exc:
        PageRequest(limit=1001)
    assert exc.value.code == ConnectorErrorCode.CONFIG_ERROR
