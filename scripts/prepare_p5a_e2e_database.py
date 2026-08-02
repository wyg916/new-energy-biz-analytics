"""Prepare a restored P5A database copy for the frozen local-auth E2E suite.

The script is intentionally narrow: it only accepts the disposable
``renewable_alpha`` database, verifies the P5 revision and simulated dataset,
then changes the three frozen local role-policy bindings from preproduction to
development. It never runs against the P5A source database and deletes no data.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.governance.models import GovernanceBinding, GovernancePolicy
from app.models.business import ChargingSession
from app.models.sales import SalesOrder, SalesOrderItem


EXPECTED_DATABASE = "renewable_alpha"
EXPECTED_REVISION = "p5_0001"
BINDING_IDS = (
    "BIND-P3-ANALYST_ADMIN",
    "BIND-P3-EXECUTIVE",
    "BIND-P3-REGIONAL_MANAGER",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if os.getenv("P5A_E2E_DATABASE_ACK") != EXPECTED_DATABASE:
        raise RuntimeError("P5A_E2E_DATABASE_ACK must explicitly name renewable_alpha")
    with SessionLocal() as db:
        database = db.scalar(text("SELECT current_database()"))
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        if database != EXPECTED_DATABASE or revision != EXPECTED_REVISION:
            raise RuntimeError(
                f"refusing non-E2E database: database={database}, revision={revision}"
            )
        counts = {
            "charging_sessions": db.scalar(select(text("count(*)")).select_from(ChargingSession)),
            "sales_orders": db.scalar(select(text("count(*)")).select_from(SalesOrder)),
            "sales_order_items": db.scalar(select(text("count(*)")).select_from(SalesOrderItem)),
        }
        if counts != {
            "charging_sessions": 300000,
            "sales_orders": 50000,
            "sales_order_items": 82514,
        }:
            raise RuntimeError(f"unexpected simulated dataset counts: {counts}")
        policy = db.get(GovernancePolicy, "POLICY-P3-PLATFORM-SCOPE-V1")
        if policy is None or policy.status != "ACTIVE" or policy.effect != "ALLOW":
            raise RuntimeError("frozen P3 platform policy is not ACTIVE ALLOW")
        bindings = list(db.scalars(select(GovernanceBinding).where(
            GovernanceBinding.binding_id.in_(BINDING_IDS)
        )).all())
        if {binding.binding_id for binding in bindings} != set(BINDING_IDS):
            raise RuntimeError("frozen local role-policy bindings are incomplete")
        before = {binding.binding_id: binding.environment for binding in bindings}
        if any(value not in {"preproduction", "development"} for value in before.values()):
            raise RuntimeError(f"unexpected binding environment: {before}")
        for binding in bindings:
            binding.environment = "development"
        db.commit()
        after = {binding.binding_id: binding.environment for binding in bindings}

    payload = {
        "status": "PASS",
        "database": database,
        "revision": revision,
        "data_classification": "simulated",
        "counts": counts,
        "bindings_before": before,
        "bindings_after": after,
        "source_database_modified": False,
        "rows_deleted": 0,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
