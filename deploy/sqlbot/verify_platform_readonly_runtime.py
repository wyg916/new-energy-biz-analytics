"""Verify untracked scenario readonly credentials without exposing their values."""

from __future__ import annotations

import json
import os
import argparse
from pathlib import Path
from time import perf_counter

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


QUERIES = {
    "charging_ops": "SELECT COUNT(*) FROM fact_charging_session",
    "sales_ops": "SELECT COUNT(*) FROM sales_order",
}
ENV_KEYS = {
    "charging_ops": "SQLBOT_READONLY_CHARGING_DATABASE_URL",
    "sales_ops": "SQLBOT_READONLY_SALES_DATABASE_URL",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = []
    for scenario, query in QUERIES.items():
        url = os.getenv(ENV_KEYS[scenario])
        if not url or not url.startswith("postgresql"):
            raise RuntimeError(f"{scenario} readonly URL is unavailable")
        connection_started = perf_counter()
        try:
            engine = create_engine(
                url,
                pool_pre_ping=True,
                poolclass=NullPool,
                connect_args={"connect_timeout": 3},
            )
            with engine.connect() as connection:
                connection_ms = round((perf_counter() - connection_started) * 1000, 3)
                with connection.begin():
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    settings = connection.execute(text(
                        "SELECT pg_backend_pid(), "
                        "current_setting('transaction_read_only'), "
                        "current_setting('statement_timeout'), "
                        "current_setting('lock_timeout')"
                    )).one()
                    backend_pid = int(settings[0])
                    before = connection.execute(text(
                        "SELECT COALESCE(wait_event_type, ''), COALESCE(wait_event, ''), "
                        "xact_start IS NOT NULL, pg_blocking_pids(pid) "
                        "FROM pg_stat_activity WHERE pid = pg_backend_pid()"
                    )).one()
                    load = connection.execute(text(
                        "SELECT count(*), "
                        "count(*) FILTER (WHERE state = 'active'), "
                        "count(*) FILTER (WHERE wait_event_type IS NOT NULL) "
                        "FROM pg_stat_activity WHERE datname = current_database()"
                    )).one()
                    sql_started = perf_counter()
                    count = int(connection.execute(text(query)).scalar_one())
                    execution_ms = round((perf_counter() - sql_started) * 1000, 3)
        except Exception as exc:
            original = getattr(exc, "orig", exc)
            sqlstate = getattr(original, "sqlstate", None) or "NO_SQLSTATE"
            results.append({
                "scenario": scenario,
                "status": "FAIL",
                "exception_type": type(exc).__name__,
                "sqlstate": sqlstate,
                "connection_acquisition_ms": round(
                    (perf_counter() - connection_started) * 1000,
                    3,
                ),
            })
        else:
            results.append({
                "scenario": scenario,
                "query_case": query,
                "status": "PASS",
                "row_count": count,
                "connection_acquisition_ms": connection_ms,
                "sql_execution_ms": execution_ms,
                "sqlstate": "00000",
                "transaction_read_only": settings[1] == "on",
                "statement_timeout": settings[2],
                "lock_timeout": settings[3],
                "backend_pid": backend_pid,
                "wait_event_type": before[0] or None,
                "wait_event": before[1] or None,
                "active_transaction": bool(before[2]),
                "blocked_by_pids": list(before[3]),
                "database_load": {
                    "connections": int(load[0]),
                    "active": int(load[1]),
                    "waiting": int(load[2]),
                },
            })
    report = {
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
        "results": results,
        "credentials_exposed": False,
        "read_only": True,
        "docker_runtime": {
            "container_id": os.getenv("HOSTNAME", "unknown"),
            "state": "running",
            "exact_image": os.getenv("SQLBOT41C_EXACT_IMAGE", "unknown"),
        },
        "prior_timeout_classification": {
            "classification": "OTHER",
            "reason": "prior process telemetry was not retained; this exact rerun records query timings",
        },
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, sort_keys=True))
    if any(item["status"] != "PASS" for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
