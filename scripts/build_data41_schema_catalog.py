"""Export a column-level DATA-4.1 Schema Catalog from SQLAlchemy metadata."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.database import Base
import app.models  # noqa: F401 - registers all tables on Base.metadata


TABLES = {
    "open_data_source": ("lineage", "Registered public source and license"),
    "open_data_snapshot": ("lineage", "Immutable downloaded or selected source snapshot"),
    "open_data_ingestion_run": ("lineage", "Idempotent raw-to-core ingestion execution"),
    "open_data_quality_check": ("lineage", "Machine-verifiable quality result per ingestion run"),
    "raw_acn_session": ("raw", "Original ORNL ACN record payload and hash"),
    "stg_acn_session": ("staging", "Normalized ACN charging session"),
    "raw_uci_retail_line": ("raw", "Original selected UCI workbook row and hash"),
    "stg_uci_retail_line": ("staging", "Normalized UCI retail invoice line"),
    "fact_charging_session": ("core", "Published charging session business fact"),
    "fact_energy_cost": ("core", "Published station-day energy-cost fact"),
    "sales_order": ("core", "Published sales order business fact"),
    "sales_order_item": ("core", "Published sales order-line business fact"),
    "metric_definition": ("semantic", "Published metric semantic definition"),
}

MEANINGS = {
    "run_id": "Auditable execution identifier",
    "source_id": "Registered public-source identifier",
    "snapshot_id": "Immutable source snapshot identifier",
    "source_hash": "SHA-256 of the downloaded source artifact",
    "snapshot_hash": "SHA-256 of the committed deterministic snapshot",
    "source_row_hash": "SHA-256 of the canonical source record",
    "data_classification": "Truth classification of the stored business row",
    "batch_id": "Published charging dataset run identifier",
    "seed_run_id": "Published sales dataset run identifier retained for compatibility",
    "energy_kwh": "Session energy delivered in kWh",
    "net_revenue": "Revenue after discount and refund",
    "gross_profit": "Net revenue less derived cost",
    "payload_json": "Lossless original source fields serialized as JSON",
}

SYNONYMS = {
    "run_id": ["ingestion run", "批次", "运行ID"],
    "station_id": ["site", "charging station", "场站"],
    "energy_kwh": ["energy", "charging volume", "充电量"],
    "net_revenue": ["sales revenue", "销售收入"],
    "service_fee_net_amount": ["charging revenue", "充电收入"],
    "invoice_no": ["order number", "订单号"],
    "source_row_hash": ["record hash", "行哈希"],
    "metric_id": ["metric code", "指标编码"],
}


def example(column) -> object:
    name = column.name
    if name.endswith("_at") or "time" in name:
        return "2020-05-09T08:15:00+00:00"
    if name.endswith("_date") or name in {"period_start", "period_end"}:
        return "2020-05-09"
    if "hash" in name:
        return "sha256:64-hex-characters"
    if name == "run_id" or name.endswith("batch_id") or name == "seed_run_id":
        return "DATA41-ACN-ORNL-26-V1"
    if "INT" in str(column.type).upper():
        return 1
    if any(token in str(column.type).upper() for token in ("NUMERIC", "DECIMAL")):
        return 46.12
    return f"example_{name}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tables = []
    relations = []
    for table_name, (layer, description) in TABLES.items():
        table = Base.metadata.tables[table_name]
        columns = []
        for column in table.columns:
            targets = sorted(str(fk.target_fullname) for fk in column.foreign_keys)
            relation = [f"{table_name}.{column.name} -> {target}" for target in targets]
            relations.extend(relation)
            sensitivity = (
                "restricted_pseudonymous"
                if column.name in {"customer_id", "source_user_id", "user_id"}
                else "restricted_raw_payload"
                if column.name == "payload_json"
                else "internal_business"
            )
            columns.append({
                "name": column.name,
                "type": str(column.type),
                "nullable": bool(column.nullable),
                "primary_key": bool(column.primary_key),
                "foreign_key": targets,
                "relation": relation,
                "description": MEANINGS.get(column.name, column.name.replace("_", " ").capitalize()),
                "business_meaning": MEANINGS.get(column.name, column.name.replace("_", " ")),
                "sensitivity": sensitivity,
                "example_value": example(column),
                "synonym": SYNONYMS.get(column.name, [column.name.replace("_", " ")]),
            })
        tables.append({
            "name": table_name,
            "layer": layer,
            "description": description,
            "query_policy": "semantic_readonly" if layer in {"core", "semantic"} else "lineage_admin_only",
            "columns": columns,
        })
    payload = {
        "catalog_version": "data41-schema-catalog-v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "database": "PostgreSQL",
        "purpose": "Governed Schema Catalog input for a future SQLBot phase; SQLBot is disabled in DATA-4.1.",
        "sqlbot_enabled": False,
        "tables": tables,
        "relations": sorted(set(relations)),
        "statistics": {
            "table_count": len(tables),
            "field_count": sum(len(table["columns"]) for table in tables),
            "relation_count": len(set(relations)),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["statistics"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
