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
        self.database = validate_identifier(
            str(config.options["database"]),
            "Database",
        )
        self.statement_timeout_ms = max(
            100,
            min(int(config.options.get("statement_timeout_ms", 10_000)), 60_000),
        )

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

    @staticmethod
    def _identifier(value: str, label: str) -> str:
        return f"`{validate_identifier(value, label)}`"

    def _database(
        self,
        selection: Selection | None = None,
        supplied: str | None = None,
    ) -> str:
        value = supplied or (selection.schema if selection else None) or self.database
        value = validate_identifier(value, "Database")
        if value != self.database:
            raise ConnectorError(
                ConnectorErrorCode.POLICY_DENIED,
                "Database 不在连接器 allowlist",
            )
        return value

    def _table(self, selection: Selection) -> str:
        if not selection.table:
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "必须选择数据表")
        return validate_identifier(selection.table, "数据表")

    def _begin_read_only(self, cursor) -> None:
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
        cursor.execute(
            "SET SESSION MAX_EXECUTION_TIME=%s",
            (self.statement_timeout_ms,),
        )

    def test_connection(self, *, timeout_seconds: int = 5, cancellation: CancellationToken | None = None) -> ConnectionTest:
        self._check(cancellation)
        started = time.perf_counter()
        connection = self._connect(timeout_seconds)
        try:
            with connection.cursor() as cursor:
                self._begin_read_only(cursor)
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
        return (CatalogItem(self.database),)

    def discover_schemas(self, catalog: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[SchemaItem, ...]:
        del catalog
        self._check(cancellation)
        return (SchemaItem(self.database, self.database),)

    def discover_tables(self, schema: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[TableItem, ...]:
        self._check(cancellation)
        database = self._database(supplied=schema)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._begin_read_only(cursor)
                cursor.execute(
                    "SELECT TABLE_NAME AS name, TABLE_TYPE AS kind FROM information_schema.tables "
                    "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
                    (database,),
                )
                rows = cursor.fetchall()
            connection.rollback()
        except ConnectorError:
            raise
        except Exception as exc:
            raise map_driver_error(exc) from exc
        finally:
            connection.close()
        return tuple(TableItem(row["name"], database, database, "view" if row["kind"] == "VIEW" else "table") for row in rows)

    def discover_columns(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[ColumnItem, ...]:
        self._check(cancellation)
        table = self._table(selection)
        database = self._database(selection)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._begin_read_only(cursor)
                cursor.execute(
                    "SELECT COLUMN_NAME AS name, DATA_TYPE AS source_type, IS_NULLABLE AS nullable, "
                    "ORDINAL_POSITION AS ordinal FROM information_schema.columns "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
                    (database, table),
                )
                rows = cursor.fetchall()
            connection.rollback()
        except ConnectorError:
            raise
        except Exception as exc:
            raise map_driver_error(exc) from exc
        finally:
            connection.close()
        if not rows:
            raise ConnectorError(
                ConnectorErrorCode.DATA_ERROR,
                "数据表不存在或没有可见字段",
            )
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

    def _read(
        self,
        selection: Selection,
        page: PageRequest,
        cancellation: CancellationToken | None,
    ) -> DataBatch:
        self._check(cancellation)
        database = self._database(selection)
        table = self._table(selection)
        available = self.discover_columns(selection, cancellation=cancellation)
        available_names = {column.name for column in available}
        selected_names = tuple(selection.columns) or tuple(
            column.name for column in available
        )
        if not selected_names or set(selected_names) - available_names:
            raise ConnectorError(
                ConnectorErrorCode.SCHEMA_DRIFT,
                "选择字段与当前数据源 Schema 不一致",
            )
        columns_sql = ", ".join(
            self._identifier(name, "字段")
            for name in selected_names
        )
        query = (
            f"SELECT {columns_sql} "
            f"FROM {self._identifier(database, 'Database')}."
            f"{self._identifier(table, '数据表')} "
            f"ORDER BY {self._identifier(selected_names[0], '字段')} "
            "LIMIT %s OFFSET %s"
        )
        connection = self._connect(
            max(1, (self.statement_timeout_ms + 999) // 1000)
        )
        try:
            with connection.cursor() as cursor:
                self._begin_read_only(cursor)
                cursor.execute(query, (page.limit, page.offset))
                rows = list(cursor.fetchall())
                self._check(cancellation)
                cursor.execute(
                    "SELECT CONCAT(@@version, ':', DATABASE()) AS source_version"
                )
                version_row = cursor.fetchone()
            connection.rollback()
        except ConnectorError:
            raise
        except Exception as exc:
            raise map_driver_error(exc) from exc
        finally:
            connection.close()
        source_version = str(
            (version_row or {}).get("source_version", "mysql-readonly")
        )
        next_offset = (
            page.offset + len(rows)
            if len(rows) == page.limit
            else None
        )
        selected_columns = tuple(
            column for column in available if column.name in selected_names
        )
        return make_batch(
            self.config.connector_id,
            selected_columns,
            rows,
            source_version=source_version,
            data_classification=str(
                self.config.options.get("data_classification", "unclassified")
            ),
            next_offset=next_offset,
        )

    def preview_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        return self._read(selection, page, cancellation)

    def profile_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> ProfileResult:
        batch = self.preview_data(selection, page, cancellation=cancellation)
        database = self._database(selection)
        table = self._table(selection)
        connection = self._connect(
            max(1, (self.statement_timeout_ms + 999) // 1000)
        )
        try:
            with connection.cursor() as cursor:
                self._begin_read_only(cursor)
                cursor.execute(
                    f"SELECT COUNT(*) AS row_count "
                    f"FROM {self._identifier(database, 'Database')}."
                    f"{self._identifier(table, '数据表')}"
                )
                row_count = int(cursor.fetchone()["row_count"])
            connection.rollback()
        except ConnectorError:
            raise
        except Exception as exc:
            raise map_driver_error(exc) from exc
        finally:
            connection.close()
        return ProfileResult(
            row_count=row_count,
            sampled_rows=batch.row_count,
            null_counts={
                column.name: sum(
                    row.get(column.name) is None for row in batch.rows
                )
                for column in batch.columns
            },
            distinct_counts={
                column.name: len(
                    {str(row.get(column.name)) for row in batch.rows}
                )
                for column in batch.columns
            },
        )

    def read_batch(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        return self._read(selection, page, cancellation)

    def read_incremental(self, selection: Selection, cursor: str | None, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        del selection, cursor, page
        self._check(cancellation)
        raise ConnectorError(
            ConnectorErrorCode.UNSUPPORTED,
            "MySQL read_incremental 尚未开放",
        )

    def health_check(self) -> HealthStatus:
        try:
            self.test_connection()
            return HealthStatus(status="ok")
        except ConnectorError as exc:
            return HealthStatus(status="error", error_code=exc.code.value)

    def close(self) -> None:
        self._closed = True
