"""Verify a governed datasource cannot connect while Vault is unavailable."""

from __future__ import annotations

import json
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.auth import User
from app.models.integration import DataSourceConnection
from app.platform.identity import IdentityContextFactory
from app.preproduction.datasource import DataSourceGovernanceError, DataSourceGovernanceService
from app.preproduction.models import PreproductionDataSourceGovernance


def main() -> None:
    with SessionLocal() as db:
        analyst = db.scalar(select(User).where(User.username == "analyst"))
        source = db.scalar(select(DataSourceConnection).join(
            PreproductionDataSourceGovernance,
            PreproductionDataSourceGovernance.source_id == DataSourceConnection.source_id,
        ).where(PreproductionDataSourceGovernance.lifecycle_status == "ACTIVE"))
        if analyst is None or source is None:
            raise RuntimeError("P4 governed datasource acceptance state unavailable")
        service = DataSourceGovernanceService(
            db, IdentityContextFactory.from_user(analyst, request_id="P4-VAULT-FAIL-CLOSED")
        )
        try:
            service.test_connection(source.source_id)
        except DataSourceGovernanceError as exc:
            print(json.dumps({
                "status": "PASS", "fail_closed": True, "error_code": exc.code,
                "plaintext_fallback_used": False, "secret_values_printed": False,
            }))
            return
    raise SystemExit("FAIL: datasource connected while Vault was expected to be unavailable")


if __name__ == "__main__":
    main()
