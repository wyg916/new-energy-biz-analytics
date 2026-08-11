"""Prepare DATA-4.1 and P6 without assuming a pre-existing Knowledge volume.

The governed Knowledge publisher requires the live OIDC/API path, so the Full
Integration launcher runs it after this init job and then rebuilds RAG.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.business_loop.metrics import MetricGovernanceService
from app.core.database import SessionLocal
from app.models.auth import User
from scripts.prepare_data41 import main as prepare_data41


def main() -> None:
    prepare_data41()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "analyst"))
        if user is None:
            raise RuntimeError(
                "P6 governance bootstrap requires the approved analyst_admin identity"
            )
        created = MetricGovernanceService(
            db, user, request_id="REQ-INTEGRATION-FULL-BOOTSTRAP",
        ).install_catalog_baseline()
    print(json.dumps({
        "status": "PASS",
        "capability": "P6 enterprise operating-management closed loops",
        "metric_governance_versions_created": created,
        "knowledge_bootstrap": "PENDING_GOVERNED_API",
        "rag_index": "PENDING_KNOWLEDGE_BOOTSTRAP",
        "sqlbot_dependency": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
