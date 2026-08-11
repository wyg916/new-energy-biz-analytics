"""Activate the 4.1C2 governed current-data Source Binding contract.

This is an automated local acceptance action, not evidence of human approval
or production activation.  The existing registry still enforces the admin
role, versioning, audit events, and reversible supersession contract.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.query_engines.sqlbot.source_binding import (
    EXPECTED_BINDINGS,
    SQLBotSourceBindingRegistry,
    install_initial_source_bindings,
)


def main() -> None:
    with SessionLocal() as db:
        user = db.scalar(
            select(User)
            .where(User.is_active.is_(True), User.role == "analyst_admin")
            .order_by(User.id)
        )
        if user is None:
            raise RuntimeError("no active controlled acceptance administrator")
        identity = IdentityContextFactory.from_user(
            user,
            request_id=(
                "SQLBOT-41C2-BINDING-"
                f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
            ),
        )
        installed = install_initial_source_bindings(db, identity)
        registry = SQLBotSourceBindingRegistry(db, identity)
        bindings = []
        for scenario_id, expected in EXPECTED_BINDINGS.items():
            active = registry.active(scenario_id)
            if active is None:
                raise RuntimeError(f"{scenario_id} has no active Source Binding")
            payload = json.loads(active.binding_json)
            relations = set(payload.get("approved_relations") or ())
            if relations != set(expected["approved_relations"]):
                raise RuntimeError(f"{scenario_id} active relation scope mismatch")
            bindings.append({
                "scenario_id": scenario_id,
                "binding_release_id": installed[scenario_id],
                "version": active.version,
                "status": active.status,
                "datasource_id": active.datasource_id,
                "relation_count": len(relations),
                "data_classification": payload.get("data_classification"),
            })
    print(json.dumps({
        "status": "PASS",
        "activation_scope": "local_full_integration_acceptance",
        "approval_mechanism": "automated_existing_admin_registry_workflow",
        "human_approval_claimed": False,
        "production_activation_claimed": False,
        "bindings": bindings,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
