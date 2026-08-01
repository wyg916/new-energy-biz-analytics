"""Persist a redacted P4 acceptance result from explicitly supplied metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.preproduction.models import PreproductionAcceptanceRecord


CATEGORIES = {
    "OIDC_INTEGRATION", "SECRET_PROVIDER", "DATASOURCE_GOVERNANCE",
    "SQLBOT_EXTERNAL", "CAPACITY_SOAK", "FAILURE_RECOVERY", "BACKUP_RESTORE",
    "SECURITY_NEGATIVE", "FRONTEND_E2E", "FULL_REGRESSION", "RELEASE_CANDIDATE",
}


def value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", choices=sorted(CATEGORIES), required=True)
    parser.add_argument("--status", choices=("PASS", "CONDITIONAL", "FAIL"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--metric", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args()
    metrics = {}
    for item in args.metric:
        if "=" not in item:
            parser.error("--metric must use KEY=VALUE")
        key, raw = item.split("=", 1)
        if not key or any(term in key.lower() for term in ("password", "token", "secret_value", "cookie", "private_key")):
            parser.error("metric key is empty or secret-bearing")
        metrics[key] = value(raw)
    metrics.update({
        "data_classification": "simulated",
        "period_start": "2025-01-01",
        "period_end_inclusive": "2026-06-30",
        "secret_values_exposed": False,
    })
    serialized = json.dumps(metrics, ensure_ascii=False, sort_keys=True)
    evidence_hash = hashlib.sha256(serialized.encode()).hexdigest()
    now = datetime.now(UTC)
    acceptance_id = "ACC-" + hashlib.sha256(f"{args.run_id}:{args.category}".encode()).hexdigest()[:36]
    with SessionLocal() as db:
        record = db.scalar(select(PreproductionAcceptanceRecord).where(
            PreproductionAcceptanceRecord.run_id == args.run_id,
            PreproductionAcceptanceRecord.category == args.category,
        ))
        if record is None:
            record = PreproductionAcceptanceRecord(
                acceptance_id=acceptance_id, run_id=args.run_id, category=args.category,
                status=args.status, environment="preproduction", metrics_json=serialized,
                evidence_hash=evidence_hash, data_classification="simulated",
                started_at=now, finished_at=now, created_by="system:p4-acceptance",
            )
            db.add(record)
        else:
            record.status = args.status
            record.metrics_json = serialized
            record.evidence_hash = evidence_hash
            record.finished_at = now
        db.commit()
    print(json.dumps({
        "category": args.category, "status": args.status, "run_id": args.run_id,
        "evidence_hash": evidence_hash, "secret_values_exposed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
