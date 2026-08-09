"""Verify untracked scenario readonly credentials without exposing their values."""

from __future__ import annotations

import json
import os
import argparse
from pathlib import Path

from sqlalchemy import create_engine, text


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
        try:
            with create_engine(url, pool_pre_ping=True).connect() as connection:
                with connection.begin():
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    count = int(connection.execute(text(query)).scalar_one())
        except Exception as exc:
            original = getattr(exc, "orig", exc)
            sqlstate = getattr(original, "sqlstate", None) or "NO_SQLSTATE"
            results.append({
                "scenario": scenario,
                "status": "FAIL",
                "exception_type": type(exc).__name__,
                "sqlstate": sqlstate,
            })
        else:
            results.append({
                "scenario": scenario,
                "status": "PASS",
                "row_count": count,
            })
    report = {
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
        "results": results,
        "credentials_exposed": False,
        "read_only": True,
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
