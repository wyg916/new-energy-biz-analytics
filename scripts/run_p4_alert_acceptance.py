"""Exercise the real local signed-webhook adapter without exposing payload details."""

from __future__ import annotations

import json
from sqlalchemy import select

from app.core.database import SessionLocal
from app.governance.models import SecurityAlert
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.preproduction.alerts import SignedWebhookAlertAdapter


def main() -> None:
    with SessionLocal() as db:
        analyst = db.scalar(select(User).where(User.username == "analyst", User.is_active.is_(True)))
        if analyst is None:
            raise RuntimeError("P4 acceptance principal unavailable")
        identity = IdentityContextFactory.from_user(analyst, request_id="P4-ALERT-ACCEPTANCE")
        alert = db.get(SecurityAlert, "ALERT-P4-LOCAL-WEBHOOK")
        if alert is None:
            alert = SecurityAlert(
                alert_id="ALERT-P4-LOCAL-WEBHOOK", tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id, rule_code="P4_LOCAL_ACCEPTANCE",
                correlation_key="p4-local-redacted", severity="medium", status="OPEN",
                event_count=1, summary="P4 local adapter acceptance only",
                trace_id="P4-ALERT-ACCEPTANCE",
            )
            db.add(alert)
            db.commit()
        adapter = SignedWebhookAlertAdapter(db, identity)
        first = adapter.deliver(alert.alert_id, idempotency_key="P4-LOCAL-WEBHOOK-IDEMPOTENCY")
        replay = adapter.deliver(alert.alert_id, idempotency_key="P4-LOCAL-WEBHOOK-IDEMPOTENCY")
    passed = (
        first["status"] == "DELIVERED" and first["payload_redacted"] is True
        and replay["idempotent_replay"] is True
    )
    print(json.dumps({
        "status": "PASS" if passed else "FAIL", "delivery_status": first["status"],
        "attempts": first["attempts"], "idempotent_replay": replay["idempotent_replay"],
        "payload_redacted": first["payload_redacted"], "secret_values_printed": False,
    }, ensure_ascii=False))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
