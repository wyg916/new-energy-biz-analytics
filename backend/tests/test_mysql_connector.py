from datetime import date, datetime
from decimal import Decimal

import pytest

from app.platform.connectors.contracts import (
    CancellationToken,
    ConnectorConfig,
    PageRequest,
    Selection,
)
from app.platform.connectors.errors import ConnectorError, ConnectorErrorCode
from app.platform.connectors.mysql import MySqlConnector
from app.platform.connectors.security import StaticCredentialProvider


pytestmark = pytest.mark.no_db


def _connector() -> MySqlConnector:
    return MySqlConnector(
        ConnectorConfig(
            connector_id="mysql-simulated",
            connector_type="mysql",
            options={
                "host": "mysql-local",
                "database": "sales_simulated",
                "user": "readonly",
                "statement_timeout_ms": 2_500,
                "data_classification": "simulated",
            },
            credential_ref="env://TEST_MYSQL_PASSWORD",
        ),
        StaticCredentialProvider({
            "env://TEST_MYSQL_PASSWORD": "test-only-value",
        }),
    )


class FakeCursor:
    def __init__(self, statements: list[tuple[str, object]]):
        self.statements = statements
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=None):
        query_text = str(query)
        self.statements.append((query_text, params))
        if "information_schema.columns" in query_text:
            assert params == ("sales_simulated", "orders")
            self.result = [
                {
                    "name": "id",
                    "source_type": "bigint",
                    "nullable": "NO",
                    "ordinal": 1,
                },
                {
                    "name": "amount",
                    "source_type": "decimal",
                    "nullable": "YES",
                    "ordinal": 2,
                },
                {
                    "name": "sold_at",
                    "source_type": "datetime",
                    "nullable": "NO",
                    "ordinal": 3,
                },
                {
                    "name": "payload",
                    "source_type": "blob",
                    "nullable": "YES",
                    "ordinal": 4,
                },
            ]
        elif query_text.startswith("SELECT `id`, `amount`"):
            assert params == (2, 1)
            self.result = [
                {"id": 2, "amount": Decimal("20.50")},
                {"id": 3, "amount": Decimal("30.75")},
            ]
        elif query_text.startswith("SELECT `id`, `sold_at`, `payload`"):
            self.result = [{
                "id": 1,
                "sold_at": datetime(2026, 7, 30, 10, 0),
                "payload": b"\x01\x02",
            }]
        elif "AS source_version" in query_text:
            self.result = [{"source_version": "8.4:test"}]
        elif query_text.startswith("SELECT COUNT(*) AS row_count"):
            self.result = [{"row_count": 3}]
        elif query_text.startswith("SELECT VERSION()"):
            self.result = [{
                "version": "8.4-test",
                "user": "readonly@%",
                "database": "sales_simulated",
            }]
        else:
            self.result = []

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None


class FakeConnection:
    def __init__(self, statements: list[tuple[str, object]]):
        self.statements = statements
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self.statements)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_mysql_preview_batch_pagination_and_normalization(monkeypatch) -> None:
    statements: list[tuple[str, object]] = []
    monkeypatch.setattr(
        "app.platform.connectors.mysql.pymysql.connect",
        lambda **_: FakeConnection(statements),
    )
    connector = _connector()

    batch = connector.read_batch(
        Selection(
            schema="sales_simulated",
            table="orders",
            columns=("id", "amount"),
        ),
        PageRequest(limit=2, offset=1),
    )
    assert batch.row_count == 2
    assert batch.rows == (
        {"id": 2, "amount": 20.5},
        {"id": 3, "amount": 30.75},
    )
    assert batch.next_offset == 3
    assert batch.source_version == "8.4:test"
    assert batch.data_classification == "simulated"
    assert tuple(column.normalized_type for column in batch.columns) == (
        "integer",
        "number",
    )
    select_query = next(
        query for query, _ in statements
        if query.startswith("SELECT `id`, `amount`")
    )
    assert (
        "FROM `sales_simulated`.`orders` "
        "ORDER BY `id` LIMIT %s OFFSET %s"
    ) in select_query
    assert any(
        query == "SET SESSION TRANSACTION READ ONLY"
        for query, _ in statements
    )
    assert any(
        query == "SET SESSION MAX_EXECUTION_TIME=%s"
        and params == (2_500,)
        for query, params in statements
    )


def test_mysql_preview_normalizes_datetime_and_binary(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.platform.connectors.mysql.pymysql.connect",
        lambda **_: FakeConnection([]),
    )
    batch = _connector().preview_data(
        Selection(
            table="orders",
            columns=("id", "sold_at", "payload"),
        ),
        PageRequest(limit=10),
    )
    assert batch.rows[0] == {
        "id": 1,
        "sold_at": "2026-07-30T10:00:00",
        "payload": "0102",
    }
    assert batch.next_offset is None


def test_mysql_profile_and_connection_health(monkeypatch) -> None:
    statements: list[tuple[str, object]] = []
    monkeypatch.setattr(
        "app.platform.connectors.mysql.pymysql.connect",
        lambda **_: FakeConnection(statements),
    )
    connector = _connector()
    profile = connector.profile_data(
        Selection(table="orders", columns=("id", "amount")),
        PageRequest(limit=2, offset=1),
    )
    assert profile.row_count == 3
    assert profile.sampled_rows == 2
    assert profile.null_counts == {"id": 0, "amount": 0}
    assert profile.distinct_counts == {"id": 2, "amount": 2}
    connection = connector.test_connection()
    assert connection.status == "ok"
    assert connection.server["read_only"] is True
    assert connector.health_check().status == "ok"


def test_mysql_rejects_cross_database_unknown_columns_and_injection(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.platform.connectors.mysql.pymysql.connect",
        lambda **_: FakeConnection([]),
    )
    connector = _connector()
    with pytest.raises(ConnectorError) as cross_database:
        connector.preview_data(
            Selection(schema="other_database", table="orders")
        )
    assert cross_database.value.code == ConnectorErrorCode.POLICY_DENIED

    with pytest.raises(ConnectorError) as unknown_column:
        connector.preview_data(
            Selection(table="orders", columns=("missing",))
        )
    assert unknown_column.value.code == ConnectorErrorCode.SCHEMA_DRIFT

    with pytest.raises(ConnectorError) as injection:
        connector.preview_data(
            Selection(table="orders; DROP TABLE orders")
        )
    assert injection.value.code == ConnectorErrorCode.POLICY_DENIED


def test_mysql_timeout_cancellation_and_incremental_status(monkeypatch) -> None:
    connector = _connector()
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ConnectorError) as cancelled:
        connector.preview_data(
            Selection(table="orders"),
            cancellation=token,
        )
    assert cancelled.value.code == ConnectorErrorCode.CANCELLED

    with pytest.raises(ConnectorError) as incremental:
        connector.read_incremental(
            Selection(table="orders", watermark_column="id"),
            cursor="1",
        )
    assert incremental.value.code == ConnectorErrorCode.UNSUPPORTED

    monkeypatch.setattr(
        "app.platform.connectors.mysql.pymysql.connect",
        lambda **_: (_ for _ in ()).throw(TimeoutError("driver timeout")),
    )
    health = connector.health_check()
    assert health.status == "error"
    assert health.error_code == ConnectorErrorCode.TIMEOUT.value


def test_mysql_type_contract_includes_date(monkeypatch) -> None:
    statements: list[tuple[str, object]] = []

    class DateCursor(FakeCursor):
        def execute(self, query, params=None):
            super().execute(query, params)
            if str(query).startswith("SELECT `id`, `sold_at`, `payload`"):
                self.result = [{
                    "id": 1,
                    "sold_at": date(2026, 7, 30),
                    "payload": b"",
                }]

    class DateConnection(FakeConnection):
        def cursor(self):
            return DateCursor(self.statements)

    monkeypatch.setattr(
        "app.platform.connectors.mysql.pymysql.connect",
        lambda **_: DateConnection(statements),
    )
    batch = _connector().preview_data(
        Selection(
            table="orders",
            columns=("id", "sold_at", "payload"),
        )
    )
    assert batch.rows[0]["sold_at"] == "2026-07-30"
