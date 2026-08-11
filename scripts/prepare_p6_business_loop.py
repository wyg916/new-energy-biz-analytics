"""Prepare Integration 4.1 data/RAG and install P6 metric governance baseline."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.business_loop.metrics import MetricGovernanceService
from app.core.database import SessionLocal
from app.models.auth import User
from scripts.prepare_integration41 import main as prepare_integration41


def main() -> None:
    prepare_integration41()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "analyst"))
        if user is None:
            raise RuntimeError("P6 governance bootstrap requires the approved analyst_admin acceptance identity")
        created = MetricGovernanceService(
            db, user, request_id="REQ-P6-BOOTSTRAP",
        ).install_catalog_baseline()
    print(json.dumps({
        "status": "PASS",
        "capability": "P6 enterprise operating-management closed loops",
        "metric_governance_versions_created": created,
        "sqlbot_dependency": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
