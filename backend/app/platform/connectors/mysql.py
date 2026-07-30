import time

import pymysql

from app.platform.connectors.base import Connector
from app.platform.connectors.capabilities import ConnectorCapabilities, IncrementalMode
from app.platform.connectors.contracts import (
    CancellationToken,
    CatalogItem,
    ColumnItem,
    ConnectionTest,
    DataBatch,
    HealthStatus,
    PageRequest,
    ProfileResult,
    RelationshipItem,
    SchemaItem,
    Selection,
    TableItem,
)
from app.platform.connectors.errors import ConnectorError, ConnectorErrorCode, map_driver_error
from app.platform.connectors.security import CredentialProvider, validate_identifier, validate_no_plaintext_credentials
from app.platform.connectors.utils import make_batch, normalize_source_type


class MySqlConnector(Connector):
    def __init__(self, config, credential_provider: CredentialProvider):
        validate_no_plaintext_credentials(config)
        self.config = config
        self.credential_provider = credential_provider
        self._closed = False
        if any(not config.options.get(key) for key in ("host", "database", "user")):
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "MySQL 配置缺少 host、database 或 user")
        if not config.credential_ref:
            raise ConnectorError(ConnectorErrorCode.CREDENTIAL_ERROR, "MySQL 需要凭据引用")

    @property
    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            catalogs=True,
            schemas=True,
            relationships=False,
            incremental_modes=(IncrementalMode.NONE,),
        )

    def _check(self, cancellation: CancellationToken | None = None) -> None:
        if cancellation:
            cancellation.raise_if_cancelled()
        if self._closed:
            raise ConnectorError(ConnectorErrorCode.SOURCE_UNAVAILABLE, "连接器已关闭")

    def _connect(self, timeout_seconds: int = 5):
        self._check()
        try:
            return pymysql.connect(
                host=self.config.options["host"],
                port=int(self.config.options.get("port", 3306)),
                database=self.config.options["database"],
                user=self.config.options["user"],
                password=self.credential_provider.resolve(self.config.credential_ref),
                connect_timeout=max(1, min(timeout_seconds, 30)),
                read_timeout=max(1, min(timeout_seconds, 30)),
                write_timeout=max(1, min(timeout_seconds, 30)),
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
            )
        except ConnectorError:
            raise
        except Exception as exc:
            raise map_driver_error(exc) from exc

    def test_connection(self, *, timeout_seconds: int = 5, cancellation: CancellationToken | None = None) -> ConnectionTest:
        self._check(cancellation)
        started = time.perf_counter()
        connection = self._connect(timeout_seconds)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
                cursor.execute("SELECT VERSION() AS version, CURRENT_USER() AS user, DATABASE() AS database")
                row = cursor.fetchone()
            connection.rollback()
        except Exception as exc:
            raise map_driver_error(exc) from exc
        finally:
            connection.close()
        return ConnectionTest(
            status="ok",
            latency_ms=int((time.perf_counter() - started) * 1000),
            server={**row, "read_only": True},
        )

    def discover_catalogs(self, *, cancellation: CancellationToken | None = None) -> tuple[CatalogItem, ...]:
        self._check(cancellation)
        return (CatalogItem(str(self.config.options["database"])),)

    def discover_schemas(self, catalog: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[SchemaItem, ...]:
        del catalog
        self._check(cancellation)
        return (SchemaItem(str(self.config.options["database"])),)

    def discover_tables(self, schema: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[TableItem, ...]:
        self._check(cancellation)
        database = schema or str(self.config.options["database"])
        if database != self.config.options["database"]:
            raise ConnectorError(ConnectorErrorCode.POLICY_DENIED, "Schema 不在连接器 allowlist")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT TABLE_NAME AS name, TABLE_TYPE AS kind FROM information_schema.tables "
                    "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
                    (database,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return tuple(TableItem(row["name"], database, database, "view" if row["kind"] == "VIEW" else "table") for row in rows)

    def discover_columns(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[ColumnItem, ...]:
        self._check(cancellation)
        if not selection.table:
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "必须选择数据表")
        validate_identifier(selection.table, "数据表")
        database = selection.schema or str(self.config.options["database"])
        if database != self.config.options["database"]:
            raise ConnectorError(ConnectorErrorCode.POLICY_DENIED, "Schema 不在连接器 allowlist")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COLUMN_NAME AS name, DATA_TYPE AS source_type, IS_NULLABLE AS nullable, "
                    "ORDINAL_POSITION AS ordinal FROM information_schema.columns "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
                    (database, selection.table),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return tuple(ColumnItem(
            row["name"],
            normalize_source_type(row["source_type"]),
            row["source_type"],
            row["nullable"] == "YES",
            row["ordinal"],
        ) for row in rows)

    def discover_relationships(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[RelationshipItem, ...]:
        del selection
        self._check(cancellation)
        return ()

    def _unsupported_data(self) -> ConnectorError:
        return ConnectorError(
            ConnectorErrorCode.UNSUPPORTED,
            "MySQL 本阶段只开放连接测试和元数据发现，数据读取默认关闭",
        )

    def preview_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        del selection, page
        self._check(cancellation)
        raise self._unsupported_data()

    def profile_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> ProfileResult:
        del selection, page
        self._check(cancellation)
        raise self._unsupported_data()

    def read_batch(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        del selection, page
        self._check(cancellation)
        raise self._unsupported_data()

    def read_incremental(self, selection: Selection, cursor: str | None, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        del selection, cursor, page
        self._check(cancellation)
        raise self._unsupported_data()

    def health_check(self) -> HealthStatus:
        try:
            self.test_connection()
            return HealthStatus(status="ok")
        except ConnectorError as exc:
            return HealthStatus(status="error", error_code=exc.code.value)

    def close(self) -> None:
        self._closed = True

