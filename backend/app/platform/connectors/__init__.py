from app.platform.connectors.csv_connector import CsvConnector
from app.platform.connectors.excel_connector import ExcelConnector
from app.platform.connectors.mock import MockConnector
from app.platform.connectors.mysql import MySqlConnector
from app.platform.connectors.postgresql import PostgreSqlConnector
from app.platform.connectors.registry import connector_registry

connector_registry.register("postgresql", PostgreSqlConnector)
connector_registry.register("csv", CsvConnector)
connector_registry.register("excel", ExcelConnector)
connector_registry.register("mysql", MySqlConnector)
connector_registry.register("mock", MockConnector)

__all__ = [
    "CsvConnector",
    "ExcelConnector",
    "MockConnector",
    "MySqlConnector",
    "PostgreSqlConnector",
    "connector_registry",
]

