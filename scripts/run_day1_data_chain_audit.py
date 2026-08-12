"""Generate read-only DAY-1 database/API-chain data-readiness evidence.

Run this inside the API container through ``scripts/p4_entrypoint.py`` so the
normal runtime secret provider supplies DATABASE_URL without exposing it.  A
``missing: false`` result means only that the required data/linkage is present;
it never asserts that a page, control, chart, or user workflow has passed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine


DEFAULT_OUTPUT_DIR = Path(
    "/app/docs/platformization/day1-functional-acceptance/evidence"
)
DEFAULT_CURRENT_START = date(2020, 5, 9)
DEFAULT_CURRENT_END = date(2020, 6, 10)
EXPECTED_MIGRATION = "integration_41_full_0001"

API_CHAINS = {
    "charging": [
        "GET /api/v1/dashboard/context",
        "GET /api/v1/dashboard/summary",
        "GET /api/v1/dashboard/stations",
        "GET /api/v1/dashboard/devices",
        "GET /api/v1/dashboard/trend",
        "GET /api/v1/revenue/analysis",
    ],
    "sales": ["POST /api/v1/assistant/query", "GET /api/v1/chat/scenarios"],
    "p6": [
        "GET|POST /api/v1/alerts",
        "GET|POST /api/v1/reports",
        "GET|POST /api/v1/metrics/governance",
    ],
    "knowledge": [
        "GET /api/v1/knowledge/runtime",
        "GET /api/v1/knowledge/documents",
        "POST /api/v1/knowledge/retrieval/test",
    ],
    "memory": ["GET|POST|PUT|DELETE /api/v1/memory/*"],
    "skills": ["GET|POST /api/v1/skills/*"],
    "data_integration": ["GET|POST /api/v1/data-integration/*"],
    "foundation": ["GET|POST /api/v1/platform/foundation/*"],
}

EXPECTED_API_ROUTES = {
    "charging": {
        ("GET", "/api/v1/dashboard/context"),
        ("GET", "/api/v1/dashboard/summary"),
        ("GET", "/api/v1/dashboard/stations"),
        ("GET", "/api/v1/dashboard/devices"),
        ("GET", "/api/v1/dashboard/trend"),
        ("GET", "/api/v1/revenue/analysis"),
    },
    "sales": {
        ("POST", "/api/v1/assistant/query"),
        ("GET", "/api/v1/chat/scenarios"),
    },
    "p6": {
        ("GET", "/api/v1/alerts"),
        ("POST", "/api/v1/alerts/generate"),
        ("GET", "/api/v1/reports"),
        ("POST", "/api/v1/reports"),
        ("GET", "/api/v1/metrics/governance"),
        ("POST", "/api/v1/metrics/governance/drafts"),
    },
    "knowledge": {
        ("GET", "/api/v1/knowledge/runtime"),
        ("GET", "/api/v1/knowledge/documents"),
        ("POST", "/api/v1/knowledge/retrieval/test"),
    },
    "memory": {
        ("GET", "/api/v1/memory/records"),
        ("GET", "/api/v1/memory/candidates"),
        ("POST", "/api/v1/memory/preferences"),
    },
    "skills": {
        ("GET", "/api/v1/skills"),
        ("POST", "/api/v1/skills/execute"),
    },
    "data_integration": {
        ("GET", "/api/v1/data-integration/overview"),
        ("POST", "/api/v1/data-integration/datasets/{dataset_id}/run"),
    },
    "foundation": {
        ("GET", "/api/v1/platform/foundation"),
        ("POST", "/api/v1/platform/foundation/datasets/{dataset_id}/versions"),
    },
}

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def scalar(conn: Connection, sql: str, **params: Any) -> Any:
    return conn.execute(text(sql), params).scalar()


def row(conn: Connection, sql: str, **params: Any) -> dict[str, Any]:
    result = conn.execute(text(sql), params).mappings().first()
    return dict(result) if result else {}


def rows(conn: Connection, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in conn.execute(text(sql), params).mappings().all()]


def table_count(conn: Connection, table: str) -> int:
    # Relation names can originate in governed source bindings.  Restrict them
    # to one unqualified SQL identifier even though the transaction is read-only.
    if not IDENTIFIER.fullmatch(table):
        raise ValueError(f"unsafe relation name in governed binding: {table!r}")
    return int(scalar(conn, f'SELECT count(*) FROM "{table}"') or 0)


def table_counts(conn: Connection, names: tuple[str, ...]) -> dict[str, int]:
    return {name: table_count(conn, name) for name in names}


def make_check(
    check_id: str,
    area: str,
    required_data: str,
    db_tables: list[str],
    evidence: dict[str, Any],
    missing: bool,
    *,
    severity: str = "required",
    note: str | None = None,
) -> dict[str, Any]:
    result = {
        "check_id": check_id,
        "area": area,
        "required_data": required_data,
        "db_tables": db_tables,
        "evidence": evidence,
        "missing": bool(missing),
        "severity": severity,
    }
    if note:
        result["note"] = note
    return result


def temporal_profile(
    conn: Connection,
    table: str,
    date_column: str,
    entity_column: str,
    current_start: date,
    current_end: date,
) -> dict[str, Any]:
    comparison_start = current_start
    current_period_start = current_start + (current_end - current_start) / 2
    return row(
        conn,
        f"""
        SELECT count(*) AS record_count,
               min({date_column}) AS min_time,
               max({date_column}) AS max_time,
               count(DISTINCT date_trunc('month', {date_column})) AS time_points,
               count(DISTINCT {entity_column}) AS ranking_entities,
               count(*) FILTER (
                   WHERE {date_column} >= :current_period_start
                     AND {date_column} < :current_end
               ) AS current_period_records,
               count(*) FILTER (
                   WHERE {date_column} >= :comparison_start
                     AND {date_column} < :current_period_start
               ) AS previous_period_records
          FROM {table}
         WHERE {date_column} IS NOT NULL
        """,
        current_period_start=current_period_start,
        current_end=current_end,
        comparison_start=comparison_start,
    )


def migration_and_runtime(conn: Connection) -> dict[str, Any]:
    from app.core.config import get_settings

    settings = get_settings()
    actual_revision = scalar(conn, "SELECT version_num FROM alembic_version")
    return {
        "migration": {
            "actual": actual_revision,
            "configured_expected": settings.expected_database_revision,
            "task_expected": EXPECTED_MIGRATION,
            "matches_configuration": actual_revision
            == settings.expected_database_revision,
            "missing": actual_revision != settings.expected_database_revision,
        },
        "runtime": {
            "app_env": settings.app_env,
            "release_version": settings.release_version,
            "runtime_data_classification": settings.runtime_data_classification,
            "active_sales_run_id": settings.active_sales_run_id or None,
            "platform_version_routing_enabled": (
                settings.effective_platform_version_routing_enabled
            ),
            "query_engine_mode": settings.effective_query_engine_mode,
            "database_dialect": conn.dialect.name,
            "database_name": scalar(conn, "SELECT current_database()"),
        },
    }


def api_route_audit() -> dict[str, Any]:
    request = urllib.request.Request(
        "http://127.0.0.1:8000/openapi.json",
        headers={"Host": "localhost"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        document = json.load(response)
    actual = {
        (method.upper(), path)
        for path, operations in document.get("paths", {}).items()
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS", "PARAMETERS"}
    }
    domains: dict[str, Any] = {}
    for domain, expected in EXPECTED_API_ROUTES.items():
        missing = sorted(expected - actual)
        domains[domain] = {
            "expected": [f"{method} {path}" for method, path in sorted(expected)],
            "missing_routes": [f"{method} {path}" for method, path in missing],
            "missing": bool(missing),
        }
    return {
        "actual_route_count": len(actual),
        "domains": domains,
        "missing": any(item["missing"] for item in domains.values()),
        "note": "Route registration only; this does not assert endpoint behavior or UI PASS.",
    }


def data_seed_audit(conn: Connection, current_start: date, current_end: date) -> dict:
    from app.core.config import get_settings

    charging_tables = (
        "dim_station",
        "dim_device",
        "fact_charging_session",
        "fact_device_status_event",
        "fact_energy_cost",
        "fact_operation_expense",
    )
    sales_tables = (
        "sales_order",
        "sales_order_item",
        "sales_region",
        "sales_channel",
        "sales_product",
        "salesperson",
    )
    p6_tables = (
        "p6_alert_event",
        "p6_alert_timeline_event",
        "p6_report",
        "p6_report_version",
        "p6_report_evidence_snapshot",
        "p6_metric_governance_version",
    )
    knowledge_tables = (
        "knowledge_document",
        "knowledge_document_version",
        "knowledge_chunk",
        "knowledge_chunk_index",
        "knowledge_retrieval_event",
    )
    memory_skill_tables = (
        "memory_record",
        "memory_write_candidate",
        "session_state",
        "procedure_definition",
        "skill_definition",
        "skill_execution",
    )
    integration_tables = (
        "data_source_connection",
        "data_set_definition",
        "data_ingestion_run",
        "data_ingestion_quality_check",
        "data_ingestion_review",
        "published_station_snapshot",
    )
    foundation_tables = (
        "dataset",
        "dataset_version",
        "mapping_version",
        "quality_result",
        "review_record",
        "release_record",
        "semantic_activation",
        "semantic_model",
        "semantic_model_version",
        "metric",
    )
    charging_profile = temporal_profile(
        conn,
        "fact_charging_session",
        "settlement_time",
        "station_id",
        current_start,
        current_end,
    )
    sales_profile = temporal_profile(
        conn,
        "sales_order",
        "order_date",
        "region_id",
        current_start,
        current_end,
    )
    active_sales_run_id = get_settings().active_sales_run_id
    active_sales_version = row(
        conn,
        """
        SELECT v.period_start, v.period_end_exclusive
          FROM dataset d
          JOIN semantic_activation a ON a.dataset_id = d.dataset_id
          JOIN dataset_version v
            ON v.dataset_version_id = a.active_dataset_version_id
         WHERE d.code = 'sales_operations'
        """,
    )
    sales_start = (
        date.fromisoformat(active_sales_version["period_start"])
        if active_sales_version.get("period_start")
        else current_start
    )
    sales_end = (
        date.fromisoformat(active_sales_version["period_end_exclusive"])
        if active_sales_version.get("period_end_exclusive")
        else current_end
    )
    sales_comparison_start = sales_start
    sales_current_start = sales_start + (sales_end - sales_start) / 2
    sales_profile = temporal_profile(
        conn, "sales_order", "order_date", "region_id", sales_start, sales_end
    )
    sales_dimensions = row(
        conn,
        """
        SELECT count(DISTINCT o.region_id) AS regions,
               count(DISTINCT o.channel_id) AS channels,
               count(DISTINCT i.product_id) AS products,
               count(DISTINCT o.salesperson_id) AS salespersons,
               count(DISTINCT o.seed_run_id) AS run_ids
          FROM sales_order o
          LEFT JOIN sales_order_item i ON i.order_id = o.order_id
         WHERE o.order_date >= :start AND o.order_date < :end
           AND (:run_id = '' OR o.seed_run_id = :run_id)
        """,
        start=sales_start,
        end=sales_end,
        run_id=active_sales_run_id,
    )
    charging_lineage = row(
        conn,
        """
        SELECT count(DISTINCT batch_id) AS run_ids,
               count(DISTINCT source_type) AS classifications,
               min(source_type) AS classification_sample
          FROM fact_charging_session
         WHERE settlement_time >= :start AND settlement_time < :end
        """,
        start=current_start,
        end=current_end,
    )
    sales_lineage = rows(
        conn,
        """
        SELECT seed_run_id AS run_id, data_classification, count(*) AS records
          FROM sales_order
         GROUP BY seed_run_id, data_classification
         ORDER BY records DESC
        """,
    )
    generation_runs = rows(
        conn,
        """
        SELECT batch_id AS run_id, generator_version, random_seed,
               period_start, period_end, status, quality_status
          FROM data_generation_run
         ORDER BY finished_at DESC NULLS LAST, started_at DESC
        """,
    )
    open_data_runs = rows(
        conn,
        """
        SELECT r.run_id, r.status, r.raw_row_count, r.staging_row_count,
               r.core_row_count, r.transformation_version,
               s.source_identifier, s.license_name, s.publisher,
               snap.dataset_version, snap.period_start, snap.period_end
          FROM open_data_ingestion_run r
          JOIN open_data_source s ON s.source_id = r.source_id
          JOIN open_data_snapshot snap ON snap.snapshot_id = r.snapshot_id
         ORDER BY r.ingestion_time DESC
        """,
    )
    domain_payloads = {
        "charging": {
            "table_counts": table_counts(conn, charging_tables),
            "temporal_profile": charging_profile,
            "lineage": charging_lineage,
        },
        "sales": {
            "table_counts": table_counts(conn, sales_tables),
            "temporal_profile": sales_profile,
            "ranking_dimensions": sales_dimensions,
            "lineage": sales_lineage,
            "current_period": {
                "start": sales_start,
                "end_exclusive": sales_end,
                "comparison_start": sales_comparison_start,
                "current_period_start": sales_current_start,
                "active_sales_run_id": active_sales_run_id or None,
            },
        },
        "p6": {"table_counts": table_counts(conn, p6_tables)},
        "knowledge": {"table_counts": table_counts(conn, knowledge_tables)},
        "memory_and_skills": {
            "table_counts": table_counts(conn, memory_skill_tables),
            "allowed_initially_empty": [
                "memory_write_candidate",
                "session_state",
                "skill_execution",
            ],
            "note": "Allowed-empty tables remain workflow targets for later UI/E2E and are not asserted PASS here.",
        },
        "data_integration": {
            "table_counts": table_counts(conn, integration_tables)
        },
        "foundation": {"table_counts": table_counts(conn, foundation_tables)},
    }
    required_by_domain = {
        "charging": set(charging_tables),
        "sales": set(sales_tables),
        "p6": set(p6_tables),
        "knowledge": {
            "knowledge_document",
            "knowledge_document_version",
            "knowledge_chunk",
            "knowledge_chunk_index",
        },
        "memory_and_skills": {
            "memory_record",
            "procedure_definition",
            "skill_definition",
        },
        "data_integration": set(integration_tables),
        "foundation": set(foundation_tables),
    }
    for domain, payload in domain_payloads.items():
        counts = payload["table_counts"]
        payload["missing"] = any(
            int(counts.get(table, 0)) < 1 for table in required_by_domain[domain]
        )
    return {
        "schema_version": "1.0",
        "evidence_type": "day1_data_seed_result",
        "read_only": True,
        "current_period": {
            "start": current_start,
            "end_exclusive": current_end,
            "comparison_start": current_start,
            "current_period_start": current_start + (current_end - current_start) / 2,
        },
        "domains": domain_payloads,
        "lineage_runs": {
            "data_generation_runs": generation_runs,
            "open_data_ingestion_runs": open_data_runs,
        },
        "missing": any(payload["missing"] for payload in domain_payloads.values()),
        "functional_pass_asserted": False,
    }


def foundation_binding_audit(conn: Connection) -> dict[str, Any]:
    bindings = rows(
        conn,
        """
        SELECT d.dataset_id, d.code, d.scenario_id, d.data_classification,
               d.source_id, d.status AS dataset_status,
               v.dataset_version_id, v.version, v.status AS version_status,
               v.source_version, v.row_count, v.period_start,
               v.period_end_exclusive, v.mapping_version_id,
               v.quality_result_id, v.source_binding_json,
               mv.status AS mapping_status, qr.status AS quality_status,
               qr.run_id AS quality_run_id,
               a.active_dataset_version_id,
               a.active_semantic_model_version_id,
               smv.version AS semantic_version,
               smv.status AS semantic_status
          FROM dataset d
          LEFT JOIN dataset_version v ON v.dataset_id = d.dataset_id
          LEFT JOIN mapping_version mv
            ON mv.mapping_version_id = v.mapping_version_id
          LEFT JOIN quality_result qr
            ON qr.quality_result_id = v.quality_result_id
          LEFT JOIN semantic_activation a ON a.dataset_id = d.dataset_id
          LEFT JOIN semantic_model_version smv
            ON smv.semantic_model_version_id = a.active_semantic_model_version_id
         ORDER BY d.code, v.version
        """,
    )
    active = [
        item
        for item in bindings
        if item["dataset_version_id"] == item["active_dataset_version_id"]
    ]
    active_checks: list[dict[str, Any]] = []
    for item in active:
        binding = json.loads(item.get("source_binding_json") or "{}")
        relations = binding.get("relations") or {}
        relation_counts = {
            relation: table_count(conn, relation)
            for relation in relations.values()
            if inspect(conn).has_table(relation)
        }
        source_run_id = (
            binding.get("run_id")
            or binding.get("source_run_id")
            or binding.get("seed_run_id")
            or item["quality_run_id"]
        )
        active_checks.append(
            {
                "dataset_code": item["code"],
                "scenario_id": item["scenario_id"],
                "dataset_version_id": item["dataset_version_id"],
                "version": item["version"],
                "data_classification": item["data_classification"],
                "source_id": item["source_id"],
                "source_version": item["source_version"],
                "source_run_id": source_run_id,
                "declared_row_count": item["row_count"],
                "period_start": item["period_start"],
                "period_end_exclusive": item["period_end_exclusive"],
                "mapping_version_id": item["mapping_version_id"],
                "mapping_status": item["mapping_status"],
                "quality_result_id": item["quality_result_id"],
                "quality_status": item["quality_status"],
                "quality_run_id": item["quality_run_id"],
                "semantic_model_version_id": item[
                    "active_semantic_model_version_id"
                ],
                "semantic_version": item["semantic_version"],
                "semantic_status": item["semantic_status"],
                "relations": relations,
                "relation_counts": relation_counts,
                "missing": any(
                    [
                        not item["data_classification"],
                        item["data_classification"] == "unclassified",
                        not item["source_version"],
                        not source_run_id,
                        not item["mapping_version_id"],
                        not item["quality_result_id"],
                        item["quality_status"] != "PASSED",
                        not item["active_semantic_model_version_id"],
                        not relations,
                        not relation_counts,
                        any(count < 1 for count in relation_counts.values()),
                    ]
                ),
            }
        )
    return {
        "all_dataset_versions": bindings,
        "active_bindings": active_checks,
        "missing": not active_checks or any(item["missing"] for item in active_checks),
    }


def missing_data_matrix(
    conn: Connection,
    seed: dict[str, Any],
    binding: dict[str, Any],
) -> dict[str, Any]:
    domains = seed["domains"]
    charging = domains["charging"]
    sales = domains["sales"]
    p6 = domains["p6"]["table_counts"]
    knowledge = domains["knowledge"]["table_counts"]
    memory = domains["memory_and_skills"]["table_counts"]
    integration = domains["data_integration"]["table_counts"]
    foundation = domains["foundation"]["table_counts"]
    cp = charging["temporal_profile"]
    sp = sales["temporal_profile"]
    sd = sales["ranking_dimensions"]
    checks = [
        make_check(
            "charging-facts",
            "dashboard/charging",
            "charging facts plus station/device dimensions",
            list(charging["table_counts"]),
            {"table_counts": charging["table_counts"]},
            any(value < 1 for value in charging["table_counts"].values()),
        ),
        make_check(
            "charging-temporal-ranking-comparison",
            "dashboard/charts/rankings",
            "more than one time point/entity and both current/comparison periods",
            ["fact_charging_session", "dim_station"],
            cp,
            int(cp["time_points"] or 0) <= 1
            or int(cp["ranking_entities"] or 0) <= 1
            or int(cp["current_period_records"] or 0) < 1
            or int(cp["previous_period_records"] or 0) < 1,
        ),
        make_check(
            "sales-facts",
            "sales_ops",
            "orders/items plus region/channel/product/salesperson dimensions",
            list(sales["table_counts"]),
            {"table_counts": sales["table_counts"]},
            any(value < 1 for value in sales["table_counts"].values()),
        ),
        make_check(
            "sales-temporal-ranking-comparison",
            "sales_ops/charts/rankings",
            "more than one time point and multiple ranking dimensions",
            ["sales_order", "sales_order_item"],
            {"temporal_profile": sp, "dimensions": sd},
            int(sp["time_points"] or 0) <= 1
            or int(sp["current_period_records"] or 0) < 1
            or int(sp["previous_period_records"] or 0) < 1
            or int(sd["regions"] or 0) <= 1
            or int(sd["products"] or 0) <= 1,
            note="The active public retail snapshot has one governed source channel; channel count is reported as a source limitation, while region and product provide valid multi-entity rankings.",
        ),
        make_check(
            "p6-alert-data",
            "alerts",
            "persisted alert and timeline evidence",
            ["p6_alert_event", "p6_alert_timeline_event"],
            {key: p6[key] for key in ("p6_alert_event", "p6_alert_timeline_event")},
            p6["p6_alert_event"] < 1 or p6["p6_alert_timeline_event"] < 1,
        ),
        make_check(
            "p6-report-data",
            "reports",
            "persisted report version and evidence snapshot",
            ["p6_report", "p6_report_version", "p6_report_evidence_snapshot"],
            {key: p6[key] for key in ("p6_report", "p6_report_version", "p6_report_evidence_snapshot")},
            any(p6[key] < 1 for key in ("p6_report", "p6_report_version", "p6_report_evidence_snapshot")),
        ),
        make_check(
            "p6-metric-governance-data",
            "metric governance",
            "persisted metric/version/status",
            ["p6_metric_governance_version"],
            {"record_count": p6["p6_metric_governance_version"]},
            p6["p6_metric_governance_version"] < 1,
        ),
        make_check(
            "knowledge-data",
            "knowledge/RAG",
            "documents, published versions, chunks and indexes",
            list(knowledge),
            knowledge,
            any(knowledge[key] < 1 for key in ("knowledge_document", "knowledge_document_version", "knowledge_chunk", "knowledge_chunk_index")),
        ),
        make_check(
            "memory-workflow-data",
            "memory",
            "persisted memory/candidate/session records for recall/delete/isolation",
            ["memory_record", "memory_write_candidate", "session_state"],
            {key: memory[key] for key in ("memory_record", "memory_write_candidate", "session_state")},
            memory["memory_record"] < 1,
            note="Candidates and session state are runtime workflow outputs and may start empty; counts remain reported but are not necessary seed gaps.",
        ),
        make_check(
            "skills-data",
            "skills",
            "procedure, skill and execution evidence",
            ["procedure_definition", "skill_definition", "skill_execution"],
            {key: memory[key] for key in ("procedure_definition", "skill_definition", "skill_execution")},
            any(memory[key] < 1 for key in ("procedure_definition", "skill_definition")),
            note="Skill execution is a runtime workflow output and may start empty.",
        ),
        make_check(
            "data-integration-data",
            "data integration",
            "source/dataset/run/quality/review/published snapshot",
            list(integration),
            integration,
            any(value < 1 for value in integration.values()),
        ),
        make_check(
            "foundation-data",
            "platform foundation",
            "dataset/version/mapping/quality/review/release/activation/semantic registry",
            list(foundation),
            foundation,
            any(value < 1 for value in foundation.values()),
        ),
        make_check(
            "active-version-binding",
            "foundation/API query context",
            "active dataset, source, classification, run/version, mapping, quality and semantic binding",
            ["dataset", "dataset_version", "mapping_version", "quality_result", "semantic_activation", "semantic_model_version"],
            binding,
            bool(binding["missing"]),
        ),
    ]
    missing = [item["check_id"] for item in checks if item["missing"]]
    return {
        "schema_version": "1.0",
        "evidence_type": "day1_missing_data_matrix",
        "read_only": True,
        "status": "MISSING_DATA" if missing else "DATA_READY",
        "missing": bool(missing),
        "summary": {
            "checks": len(checks),
            "missing_checks": len(missing),
            "missing_check_ids": missing,
        },
        "checks": checks,
        "functional_pass_asserted": False,
    }


def kpi_audit(conn: Connection, current_start: date, current_end: date) -> dict:
    from app.core.config import get_settings
    from app.scenarios.sales_ops.metrics import SALES_METRICS

    comparison_start = current_start
    current_period_start = current_start + (current_end - current_start) / 2
    charging = row(
        conn,
        """
        SELECT count(DISTINCT session_id) FILTER (
                   WHERE settlement_time >= :current_start AND settlement_time < :current_end
               ) AS current_orders,
               count(DISTINCT session_id) FILTER (
                   WHERE settlement_time >= :previous_start AND settlement_time < :current_start
               ) AS previous_orders,
               coalesce(sum(electricity_fee_net_amount + service_fee_net_amount) FILTER (
                   WHERE settlement_time >= :current_start AND settlement_time < :current_end
               ), 0) AS current_revenue,
               coalesce(sum(electricity_fee_net_amount + service_fee_net_amount) FILTER (
                   WHERE settlement_time >= :previous_start AND settlement_time < :current_start
               ), 0) AS previous_revenue,
               count(DISTINCT date_trunc('month', settlement_time)) FILTER (
                   WHERE settlement_time >= :previous_start AND settlement_time < :current_end
               ) AS trend_points
          FROM fact_charging_session
         WHERE session_status = 'completed'
        """,
        current_start=current_period_start,
        current_end=current_end,
        previous_start=comparison_start,
    )
    active_sales = row(
        conn,
        """
        SELECT v.period_start, v.period_end_exclusive
          FROM dataset d
          JOIN semantic_activation a ON a.dataset_id = d.dataset_id
          JOIN dataset_version v ON v.dataset_version_id = a.active_dataset_version_id
         WHERE d.code = 'sales_operations'
        """,
    )
    sales_start = date.fromisoformat(active_sales["period_start"])
    sales_end = date.fromisoformat(active_sales["period_end_exclusive"])
    sales_comparison_start = sales_start
    sales_current_start = sales_start + (sales_end - sales_start) / 2
    active_sales_run_id = get_settings().active_sales_run_id
    sales = row(
        conn,
        """
        SELECT count(*) FILTER (
                   WHERE order_date >= :current_start AND order_date < :current_end
               ) AS current_orders,
               count(*) FILTER (
                   WHERE order_date >= :previous_start AND order_date < :current_start
               ) AS previous_orders,
               coalesce(sum(net_revenue) FILTER (
                   WHERE order_date >= :current_start AND order_date < :current_end
               ), 0) AS current_revenue,
               coalesce(sum(net_revenue) FILTER (
                   WHERE order_date >= :previous_start AND order_date < :current_start
               ), 0) AS previous_revenue,
               count(DISTINCT date_trunc('month', order_date)) FILTER (
                   WHERE order_date >= :previous_start AND order_date < :current_end
               ) AS trend_points
          FROM sales_order
         WHERE status IN ('completed', 'refunded')
           AND (:run_id = '' OR seed_run_id = :run_id)
        """,
        current_start=sales_current_start,
        current_end=sales_end,
        previous_start=sales_comparison_start,
        run_id=active_sales_run_id,
    )
    charging_metrics = table_count(conn, "metric_definition")
    sales_metrics = len(SALES_METRICS)
    checks = {
        "charging": {
            "values": charging,
            "registered_metric_definitions": charging_metrics,
            "missing": charging_metrics < 15
            or int(charging["current_orders"] or 0) < 1
            or int(charging["previous_orders"] or 0) < 1
            or int(charging["trend_points"] or 0) <= 1,
        },
        "sales": {
            "values": sales,
            "period": {
                "current_start": sales_current_start,
                "current_end_exclusive": sales_end,
                "previous_start": sales_comparison_start,
                "active_sales_run_id": active_sales_run_id or None,
            },
            "implemented_metric_catalog_size": sales_metrics,
            "catalog_source": "app.scenarios.sales_ops.metrics.SALES_METRICS",
            "missing": int(sales["current_orders"] or 0) < 1
            or int(sales["previous_orders"] or 0) < 1
            or int(sales["trend_points"] or 0) <= 1,
        },
    }
    return {
        "schema_version": "1.0",
        "evidence_type": "day1_kpi_data_audit",
        "read_only": True,
        "period": {
            "current_start": current_period_start,
            "current_end_exclusive": current_end,
            "previous_start": comparison_start,
            "comparison_basis": "selected source window split into equal consecutive halves",
        },
        "checks": checks,
        "missing": any(item["missing"] for item in checks.values()),
        "functional_pass_asserted": False,
    }


def chart_audit(conn: Connection, current_start: date, current_end: date) -> dict:
    from app.core.config import get_settings

    active_sales = row(
        conn,
        """
        SELECT v.period_start, v.period_end_exclusive
          FROM dataset d
          JOIN semantic_activation a ON a.dataset_id = d.dataset_id
          JOIN dataset_version v ON v.dataset_version_id = a.active_dataset_version_id
         WHERE d.code = 'sales_operations'
        """,
    )
    sales_start = date.fromisoformat(active_sales["period_start"])
    sales_end = date.fromisoformat(active_sales["period_end_exclusive"])
    active_sales_run_id = get_settings().active_sales_run_id
    profiles = {
        "charging_monthly_trend": row(
            conn,
            """
            SELECT count(DISTINCT date_trunc('month', settlement_time)) AS data_points,
                   min(settlement_time) AS min_time,
                   max(settlement_time) AS max_time
              FROM fact_charging_session
             WHERE settlement_time >= :start AND settlement_time < :end
            """,
            start=current_start,
            end=current_end,
        ),
        "charging_station_ranking": row(
            conn,
            """
            SELECT count(DISTINCT station_id) AS entities,
                   count(*) AS records
              FROM fact_charging_session
             WHERE settlement_time >= :start AND settlement_time < :end
            """,
            start=current_start,
            end=current_end,
        ),
        "device_status_trend": row(
            conn,
            """
            SELECT count(DISTINCT date_trunc('month', start_time)) AS data_points,
                   count(DISTINCT device_id) AS entities,
                   count(*) AS records
              FROM fact_device_status_event e
             WHERE e.start_time >= :start AND e.start_time < :end
            """,
            start=scalar(conn, "SELECT min(start_time) FROM fact_device_status_event"),
            end=scalar(conn, "SELECT max(end_time) FROM fact_device_status_event")
            + timedelta(microseconds=1),
        ),
        "sales_monthly_trend": row(
            conn,
            """
            SELECT count(DISTINCT date_trunc('month', order_date)) AS data_points,
                   min(order_date) AS min_time,
                   max(order_date) AS max_time
              FROM sales_order
             WHERE order_date >= :start AND order_date < :end
               AND (:run_id = '' OR seed_run_id = :run_id)
            """,
            start=sales_start,
            end=sales_end,
            run_id=active_sales_run_id,
        ),
        "sales_rankings": row(
            conn,
            """
            SELECT count(DISTINCT o.region_id) AS regions,
                   count(DISTINCT o.channel_id) AS channels,
                   count(DISTINCT i.product_id) AS products
              FROM sales_order o
              JOIN sales_order_item i ON i.order_id = o.order_id
             WHERE o.order_date >= :start AND o.order_date < :end
               AND (:run_id = '' OR o.seed_run_id = :run_id)
            """,
            start=sales_start,
            end=sales_end,
            run_id=active_sales_run_id,
        ),
    }
    checks = [
        {
            "chart_family": name,
            "evidence": evidence,
            "missing": any(
                int(value or 0) <= 1
                for key, value in evidence.items()
                if key in {"data_points", "entities", "regions", "products"}
            ),
            "note": "DB readiness only; browser rendering, tooltip, filters and refresh require E2E.",
        }
        for name, evidence in profiles.items()
    ]
    return {
        "schema_version": "1.0",
        "evidence_type": "day1_chart_data_audit",
        "read_only": True,
        "checks": checks,
        "missing": any(item["missing"] for item in checks),
        "functional_pass_asserted": False,
    }


def chain_audit(
    conn: Connection,
    runtime: dict[str, Any],
    seed: dict[str, Any],
    matrix: dict[str, Any],
    kpis: dict[str, Any],
    charts: dict[str, Any],
    binding: dict[str, Any],
    api_routes: dict[str, Any],
) -> dict[str, Any]:
    route_rows = rows(
        conn,
        """
        SELECT scenario AS scenario_id, count(*) AS decisions,
               count(*) FILTER (WHERE run_id IS NOT NULL) AS with_run_id
          FROM query_route_decision
         GROUP BY scenario
         ORDER BY scenario
        """,
    )
    sources = rows(
        conn,
        """
        SELECT source_id, display_name, source_type, status,
               last_tested_at, last_error_code
          FROM data_source_connection
         ORDER BY source_id
        """,
    )
    missing_sections = {
        "migration": runtime["migration"]["missing"],
        "missing_data_matrix": matrix["summary"]["missing_checks"] > 0,
        "kpi_data": kpis["missing"],
        "chart_data": charts["missing"],
        "active_version_binding": binding["missing"],
        "api_route_registration": api_routes["missing"],
    }
    return {
        "schema_version": "1.0",
        "evidence_type": "day1_db_api_chain_audit",
        "captured_at": datetime.now(UTC),
        "read_only": True,
        "transaction_mode": "database transaction explicitly SET TRANSACTION READ ONLY and rolled back",
        "runtime": runtime,
        "api_chains": API_CHAINS,
        "api_route_registration": api_routes,
        "database_sources": sources,
        "query_route_evidence": route_rows,
        "active_version_binding": binding,
        "artifacts": {
            "data_seed_result": {
                "domains": sorted(seed["domains"]),
                "functional_pass_asserted": False,
            },
            "missing_data_matrix": matrix["summary"],
            "kpi_audit_missing": kpis["missing"],
            "chart_audit_missing": charts["missing"],
        },
        "missing_sections": missing_sections,
        "missing": any(missing_sections.values()),
        "adjudication": (
            "DATA_CHAIN_MISSING"
            if any(missing_sections.values())
            else "DATA_CHAIN_READY_FOR_FUNCTIONAL_TESTING"
        ),
        "functional_pass_asserted": False,
        "warning": "Record counts and data readiness must not be converted into page/control/user-visible-function PASS.",
    }


def render(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=json_value) + "\n"


def write_artifacts(output_dir: Path, artifacts: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in artifacts.items():
        (output_dir / name).write_text(render(payload), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory for five JSON artifacts (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--current-start",
        type=date.fromisoformat,
        default=DEFAULT_CURRENT_START,
        help="current comparison window start, YYYY-MM-DD (default: 2020-05-09)",
    )
    parser.add_argument(
        "--current-end-exclusive",
        type=date.fromisoformat,
        default=DEFAULT_CURRENT_END,
        help="current comparison window exclusive end, YYYY-MM-DD (default: 2020-06-10)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="also print the complete db-api-chain-audit.json payload to stdout",
    )
    return parser


def run(db_engine: Engine, args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    if args.current_start >= args.current_end_exclusive:
        raise ValueError("--current-start must be before --current-end-exclusive")
    with db_engine.connect() as conn:
        transaction = conn.begin()
        try:
            if conn.dialect.name != "postgresql":
                raise RuntimeError("DAY-1 audit requires the current PostgreSQL runtime")
            conn.execute(text("SET TRANSACTION READ ONLY"))
            runtime = migration_and_runtime(conn)
            api_routes = api_route_audit()
            seed = data_seed_audit(conn, args.current_start, args.current_end_exclusive)
            binding = foundation_binding_audit(conn)
            matrix = missing_data_matrix(conn, seed, binding)
            kpis = kpi_audit(conn, args.current_start, args.current_end_exclusive)
            charts = chart_audit(conn, args.current_start, args.current_end_exclusive)
            chain = chain_audit(
                conn, runtime, seed, matrix, kpis, charts, binding, api_routes
            )
        finally:
            transaction.rollback()
    artifacts = {
        "missing-data-matrix.json": matrix,
        "data-seed-result.json": seed,
        "kpi-audit.json": kpis,
        "chart-audit.json": charts,
        "db-api-chain-audit.json": chain,
    }
    write_artifacts(args.output_dir, artifacts)
    return artifacts, bool(chain["missing"])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from app.core.database import engine

        artifacts, missing = run(engine, args)
    except Exception as exc:  # Preserve concise CI/container diagnostics.
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "read_only": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    chain = artifacts["db-api-chain-audit.json"]
    summary = {
        "status": chain["adjudication"],
        "missing": missing,
        "missing_check_ids": artifacts["missing-data-matrix.json"]["summary"]["missing_check_ids"],
        "output_dir": str(args.output_dir),
        "files": sorted(artifacts),
        "functional_pass_asserted": False,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if args.stdout:
        print(render(chain), end="")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
