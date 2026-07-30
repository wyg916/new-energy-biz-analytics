import time

import psycopg
from psycopg import sql

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
from app.platform.connectors.security import (
    CredentialProvider,
    validate_identifier,
    validate_no_plaintext_credentials,
)
from app.platform.connectors.utils import make_batch, normalize_source_type


class PostgreSqlConnector(Connector):
    def __init__(self, config, credential_provider: CredentialProvider):
        validate_no_plaintext_credentials(config)
        self.config = config
        self.credential_provider = credential_provider
        self._closed = False
        required = ("host", "database", "user")
        if any(not isinstance(config.options.get(key), str) or not config.options.get(key) for key in required):
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "PostgreSQL 配置缺少 host、database 或 user")
        if not config.credential_ref:
            raise ConnectorError(ConnectorErrorCode.CREDENTIAL_ERROR, "PostgreSQL 需要凭据引用")
        self.allowed_schemas = tuple(config.options.get("allowed_schemas", ("public",)))
        for schema in self.allowed_schemas:
            validate_identifier(schema, "Schema")

    @property
    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            catalogs=True,
            schemas=True,
            relationships=True,
            incremental_modes=(IncrementalMode.NONE, IncrementalMode.TIMESTAMP, IncrementalMode.WATERMARK),
        )

    def _check(self, cancellation: CancellationToken | None = None) -> None:
        if cancellation:
            cancellation.raise_if_cancelled()
        if self._closed:
            raise ConnectorError(ConnectorErrorCode.SOURCE_UNAVAILABLE, "连接器已关闭")

    def _connect(self, timeout_seconds: int = 5):
        self._check()
        try:
            password = self.credential_provider.resolve(self.config.credential_ref)
            connection = psycopg.connect(
                host=self.config.options["host"],
                port=int(self.config.options.get("port", 5432)),
                dbname=self.config.options["database"],
                user=self.config.options["user"],
                password=password,
                connect_timeout=max(1, min(timeout_seconds, 30)),
                sslmode=str(self.config.options.get("sslmode", "prefer")),
                options="-c default_transaction_read_only=on",
            )
            statement_timeout = int(self.config.options.get("statement_timeout_ms", 10000))
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('statement_timeout', %s, false)", (str(statement_timeout),))
            return connection
        except ConnectorError:
            raise
        except Exception as exc:
            raise map_driver_error(exc) from exc

    def _schema(self, selection: Selection | None = None, supplied: str | None = None) -> str:
        value = supplied or (selection.schema if selection else None) or self.allowed_schemas[0]
        validate_identifier(value, "Schema")
        if value not in self.allowed_schemas:
            raise ConnectorError(ConnectorErrorCode.POLICY_DENIED, "Schema 不在连接器 allowlist")
        return value

    def _table(self, selection: Selection) -> str:
        if not selection.table:
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "必须选择数据表")
        return validate_identifier(selection.table, "数据表")

    def test_connection(self, *, timeout_seconds: int = 5, cancellation: CancellationToken | None = None) -> ConnectionTest:
        self._check(cancellation)
        started = time.perf_counter()
        try:
            with self._connect(timeout_seconds) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_database(), current_user, current_setting('server_version')")
                    database, user, version = cursor.fetchone()
            return ConnectionTest(
                status="ok",
                latency_ms=int((time.perf_counter() - started) * 1000),
                server={"database": database, "user": user, "version": version, "read_only": True},
            )
        except ConnectorError:
            raise
        except Exception as exc:
            raise map_driver_error(exc) from exc

    def discover_catalogs(self, *, cancellation: CancellationToken | None = None) -> tuple[CatalogItem, ...]:
        self._check(cancellation)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database()")
                return (CatalogItem(name=cursor.fetchone()[0]),)

    def discover_schemas(self, catalog: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[SchemaItem, ...]:
        self._check(cancellation)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name = ANY(%s) ORDER BY schema_name",
                    (list(self.allowed_schemas),),
                )
                return tuple(SchemaItem(name=row[0], catalog=catalog) for row in cursor.fetchall())

    def discover_tables(self, schema: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[TableItem, ...]:
        self._check(cancellation)
        selected_schema = self._schema(supplied=schema)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT table_name, table_type FROM information_schema.tables "
                    "WHERE table_schema = %s ORDER BY table_name",
                    (selected_schema,),
                )
                return tuple(TableItem(
                    name=name,
                    schema=selected_schema,
                    catalog=self.config.options["database"],
                    kind="view" if kind == "VIEW" else "table",
                ) for name, kind in cursor.fetchall())

    def discover_columns(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[ColumnItem, ...]:
        self._check(cancellation)
        selected_schema, selected_table = self._schema(selection), self._table(selection)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT column_name, data_type, is_nullable, ordinal_position "
                    "FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                    "ORDER BY ordinal_position",
                    (selected_schema, selected_table),
                )
                rows = cursor.fetchall()
        if not rows:
            raise ConnectorError(ConnectorErrorCode.DATA_ERROR, "数据表不存在或没有可见字段")
        return tuple(ColumnItem(
            name=name,
            normalized_type=normalize_source_type(source_type),
            source_type=source_type,
            nullable=nullable == "YES",
            ordinal=ordinal,
        ) for name, source_type, nullable, ordinal in rows)

    def discover_relationships(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[RelationshipItem, ...]:
        self._check(cancellation)
        selected_schema, selected_table = self._schema(selection), self._table(selection)
        query = """
            SELECT constraint_record.conname, source_attribute.attname,
                   target_table.relname, target_attribute.attname
            FROM pg_catalog.pg_constraint AS constraint_record
            JOIN pg_catalog.pg_class AS source_table
              ON source_table.oid = constraint_record.conrelid
            JOIN pg_catalog.pg_namespace AS source_namespace
              ON source_namespace.oid = source_table.relnamespace
            JOIN pg_catalog.pg_class AS target_table
              ON target_table.oid = constraint_record.confrelid
            JOIN LATERAL unnest(constraint_record.conkey)
              WITH ORDINALITY AS source_key(attnum, ordinal) ON TRUE
            JOIN LATERAL unnest(constraint_record.confkey)
              WITH ORDINALITY AS target_key(attnum, ordinal)
              ON target_key.ordinal = source_key.ordinal
            JOIN pg_catalog.pg_attribute AS source_attribute
              ON source_attribute.attrelid = source_table.oid
             AND source_attribute.attnum = source_key.attnum
            JOIN pg_catalog.pg_attribute AS target_attribute
              ON target_attribute.attrelid = target_table.oid
             AND target_attribute.attnum = target_key.attnum
            WHERE constraint_record.contype = 'f'
              AND source_namespace.nspname = %s
              AND source_table.relname = %s
            ORDER BY constraint_record.conname, source_key.ordinal
        """
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, (selected_schema, selected_table))
                rows = cursor.fetchall()
        return tuple(RelationshipItem(
            name=name,
            source_table=selected_table,
            source_columns=(source_column,),
            target_table=target_table,
            target_columns=(target_column,),
        ) for name, source_column, target_table, target_column in rows)

    def _read(
        self,
        selection: Selection,
        page: PageRequest,
        cancellation: CancellationToken | None,
        cursor_value: str | None = None,
    ) -> DataBatch:
        self._check(cancellation)
        selected_schema, selected_table = self._schema(selection), self._table(selection)
        available = self.discover_columns(selection, cancellation=cancellation)
        available_names = {column.name for column in available}
        selected_names = tuple(selection.columns) or tuple(column.name for column in available)
        if not selected_names or set(selected_names) - available_names:
            raise ConnectorError(ConnectorErrorCode.SCHEMA_DRIFT, "选择字段与当前数据源 Schema 不一致")
        for name in selected_names:
            validate_identifier(name, "字段")
        column_sql = sql.SQL(", ").join(sql.Identifier(name) for name in selected_names)
        query = sql.SQL("SELECT {columns} FROM {schema}.{table}").format(
            columns=column_sql,
            schema=sql.Identifier(selected_schema),
            table=sql.Identifier(selected_table),
        )
        params: list[object] = []
        if selection.watermark_column:
            if selection.watermark_column not in available_names:
                raise ConnectorError(ConnectorErrorCode.SCHEMA_DRIFT, "增量字段不存在")
            if cursor_value is not None:
                query += sql.SQL(" WHERE {} > %s").format(sql.Identifier(selection.watermark_column))
                params.append(cursor_value)
            query += sql.SQL(" ORDER BY {}").format(sql.Identifier(selection.watermark_column))
        else:
            query += sql.SQL(" ORDER BY 1")
        query += sql.SQL(" LIMIT %s OFFSET %s")
        params.extend((page.limit, 0 if selection.watermark_column else page.offset))
        with self._connect() as connection:
            with connection.cursor() as database_cursor:
                database_cursor.execute(query, tuple(params))
                rows = [dict(zip(selected_names, row, strict=True)) for row in database_cursor.fetchall()]
                database_cursor.execute("SELECT txid_current_snapshot()::text")
                source_version = database_cursor.fetchone()[0]
        next_cursor = (
            str(rows[-1][selection.watermark_column])
            if rows and selection.watermark_column
            else cursor_value
        )
        next_offset = page.offset + len(rows) if len(rows) == page.limit and not selection.watermark_column else None
        selected_columns = tuple(column for column in available if column.name in selected_names)
        return make_batch(
            self.config.connector_id,
            selected_columns,
            rows,
            source_version=source_version,
            data_classification=str(self.config.options.get("data_classification", "unclassified")),
            cursor=next_cursor,
            next_offset=next_offset,
        )

    def preview_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        return self._read(selection, page, cancellation)

    def read_batch(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        return self._read(selection, page, cancellation)

    def read_incremental(self, selection: Selection, cursor: str | None, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        if not selection.watermark_column:
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "增量读取需要 watermark_column")
        return self._read(selection, page, cancellation, cursor)

    def profile_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> ProfileResult:
        batch = self.preview_data(selection, page, cancellation=cancellation)
        selected_schema, selected_table = self._schema(selection), self._table(selection)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                        sql.Identifier(selected_schema), sql.Identifier(selected_table)
                    )
                )
                row_count = int(cursor.fetchone()[0])
        return ProfileResult(
            row_count=row_count,
            sampled_rows=batch.row_count,
            null_counts={column.name: sum(row.get(column.name) is None for row in batch.rows) for column in batch.columns},
            distinct_counts={column.name: len({str(row.get(column.name)) for row in batch.rows}) for column in batch.columns},
        )

    def health_check(self) -> HealthStatus:
        try:
            self.test_connection()
            return HealthStatus(status="ok")
        except ConnectorError as exc:
            return HealthStatus(status="error", error_code=exc.code.value)

    def close(self) -> None:
        self._closed = True
