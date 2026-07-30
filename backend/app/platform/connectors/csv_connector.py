import csv

from app.platform.connectors.contracts import CancellationToken, ColumnItem, DataBatch, PageRequest, Selection, TableItem
from app.platform.connectors.errors import ConnectorError, ConnectorErrorCode
from app.platform.connectors.file_base import FileConnector


class CsvConnector(FileConnector):
    suffixes = {".csv"}

    def _read(self, page: PageRequest | None, cancellation: CancellationToken | None) -> tuple[list[str], list[dict], int]:
        self._check(cancellation)
        encoding = str(self.config.options.get("encoding", "utf-8-sig"))
        try:
            with self.path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                headers = list(reader.fieldnames or [])
                all_rows = []
                for index, row in enumerate(reader):
                    if cancellation and index % 100 == 0:
                        cancellation.raise_if_cancelled()
                    all_rows.append(dict(row))
            if not headers:
                raise ConnectorError(ConnectorErrorCode.DATA_ERROR, "CSV 缺少表头")
            rows = all_rows if page is None else all_rows[page.offset:page.offset + page.limit]
            return headers, rows, len(all_rows)
        except UnicodeError as exc:
            raise ConnectorError(ConnectorErrorCode.DATA_ERROR, "CSV 编码无法解析") from exc

    def discover_tables(self, schema: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[TableItem, ...]:
        del schema
        self._check(cancellation)
        return (TableItem(name=self.path.stem, schema="file"),)

    def discover_columns(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[ColumnItem, ...]:
        del selection
        headers, rows, _ = self._read(PageRequest(limit=100), cancellation)
        return self._columns_from_rows(headers, rows)

    def read_batch(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        del selection
        headers, rows, total = self._read(page, cancellation)
        return self._batch(self._columns_from_rows(headers, rows), rows, page, total)

    def total_rows(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> int:
        del selection
        return self._read(None, cancellation)[2]

