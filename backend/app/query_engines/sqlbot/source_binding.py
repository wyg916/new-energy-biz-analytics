from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.memory.audit import audit_memory_use
from app.memory.models import SQLBotSourceBindingRelease
from app.data.truth import current_data_truth
from app.platform.identity import IdentityContext


EXPECTED_BINDINGS = {
    "charging_ops": {
        "datasource_id": "1",
        "approved_relations": (
            "active_context", "dim_station", "fact_charging_session",
            "fact_device_status_event", "fact_energy_cost",
            "fact_operation_expense",
        ),
    },
    "sales_ops": {
        "datasource_id": "2",
        "approved_relations": (
            "active_context", "sales_business_date", "sales_channel",
            "sales_customer", "sales_order", "sales_order_item",
            "sales_product", "sales_product_category", "sales_region",
            "salesperson",
        ),
    },
}
EXPECTED_DATASOURCES = {
    scenario_id: spec["datasource_id"] for scenario_id, spec in EXPECTED_BINDINGS.items()
}


class SourceBindingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _reviewer(identity: IdentityContext) -> None:
    if "analyst_admin" not in identity.roles:
        raise SourceBindingError("BINDING_REVIEW_REQUIRED", "仅管理员可审批或激活 SQLBot Source Binding")


class SQLBotSourceBindingRegistry:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def register(
        self,
        *,
        scenario_id: str,
        datasource_id: str,
        run_id: str,
    ) -> SQLBotSourceBindingRelease:
        spec = EXPECTED_BINDINGS.get(scenario_id)
        expected = spec["datasource_id"] if spec else None
        if expected is None or str(datasource_id) != expected:
            raise SourceBindingError("BINDING_NOT_ALLOWLISTED", "场景与 SQLBot Datasource 绑定不在冻结白名单")
        latest = self.db.scalar(select(func.max(SQLBotSourceBindingRelease.version)).where(
            SQLBotSourceBindingRelease.scenario_id == scenario_id
        ))
        row = SQLBotSourceBindingRelease(
            binding_release_id=f"SQLBOT-BIND-{uuid4()}",
            scenario_id=scenario_id,
            datasource_id=expected,
            version=int(latest or 0) + 1,
            status="DRAFT",
            binding_json=json.dumps(
                {
                    "scenario_id": scenario_id,
                    "datasource_id": expected,
                    "execution_mode": "upstream_readonly",
                    "approved_relations": list(spec["approved_relations"]),
                    "deterministic_engine_unchanged": True,
                    "data_classification": current_data_truth(self.db)["data_classification"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            run_id=run_id,
        )
        self.db.add(row)
        self._audit(row, "sqlbot.binding.register", "draft")
        self.db.commit()
        return row

    def approve(self, binding_release_id: str) -> SQLBotSourceBindingRelease:
        _reviewer(self.identity)
        row = self._get(binding_release_id)
        if row.status != "DRAFT":
            raise SourceBindingError("BINDING_INVALID_TRANSITION", "仅 DRAFT Source Binding 可审批")
        row.status = "APPROVED"
        row.approved_by = self.identity.subject_id
        row.approved_at = datetime.now(UTC)
        self._audit(row, "sqlbot.binding.approve", "success")
        self.db.commit()
        return row

    def activate(self, binding_release_id: str) -> SQLBotSourceBindingRelease:
        _reviewer(self.identity)
        row = self._get(binding_release_id)
        if row.status != "APPROVED" or not row.approved_by:
            raise SourceBindingError("BINDING_NOT_APPROVED", "未经人工审批的 Source Binding 不得 ACTIVE")
        active = self.active(row.scenario_id)
        if active is not None and active.binding_release_id != row.binding_release_id:
            active.status = "SUPERSEDED"
            self.db.flush()
        row.status = "ACTIVE"
        row.activated_by = self.identity.subject_id
        row.activated_at = datetime.now(UTC)
        self._audit(row, "sqlbot.binding.activate", "success")
        self.db.commit()
        return row

    def rollback(
        self,
        *,
        scenario_id: str,
        target_binding_release_id: str,
        run_id: str,
    ) -> SQLBotSourceBindingRelease:
        _reviewer(self.identity)
        current = self.active(scenario_id)
        target = self._get(target_binding_release_id)
        if target.scenario_id != scenario_id or target.approved_by is None:
            raise SourceBindingError("BINDING_ROLLBACK_TARGET_INVALID", "回滚目标场景不一致或未经批准")
        rollback = self.register(
            scenario_id=scenario_id,
            datasource_id=target.datasource_id,
            run_id=run_id,
        )
        rollback.rollback_of_id = current.binding_release_id if current else None
        rollback.status = "APPROVED"
        rollback.approved_by = self.identity.subject_id
        rollback.approved_at = datetime.now(UTC)
        self.db.commit()
        return self.activate(rollback.binding_release_id)

    def active(self, scenario_id: str) -> SQLBotSourceBindingRelease | None:
        return self.db.scalar(select(SQLBotSourceBindingRelease).where(
            SQLBotSourceBindingRelease.scenario_id == scenario_id,
            SQLBotSourceBindingRelease.status == "ACTIVE",
        ).order_by(desc(SQLBotSourceBindingRelease.version)))

    def _get(self, binding_release_id: str) -> SQLBotSourceBindingRelease:
        row = self.db.get(SQLBotSourceBindingRelease, binding_release_id)
        if row is None:
            raise SourceBindingError("BINDING_NOT_FOUND", "SQLBot Source Binding 不存在")
        return row

    def _audit(self, row: SQLBotSourceBindingRelease, action: str, outcome: str) -> None:
        audit_memory_use(
            self.db,
            self.identity,
            action=action,
            outcome=outcome,
            run_id=row.run_id,
            detail={
                "binding_release_id": row.binding_release_id,
                "scenario_id": row.scenario_id,
                "datasource_id": row.datasource_id,
                "version": row.version,
            },
        )


def install_initial_source_bindings(db: Session, identity: IdentityContext) -> dict[str, str]:
    registry = SQLBotSourceBindingRegistry(db, identity)
    installed: dict[str, str] = {}
    for scenario_id, datasource_id in EXPECTED_DATASOURCES.items():
        active = registry.active(scenario_id)
        spec = EXPECTED_BINDINGS[scenario_id]
        active_payload = json.loads(active.binding_json) if active is not None else {}
        active_relations = set(active_payload.get("approved_relations") or ())
        expected_relations = set(spec["approved_relations"])
        expected_classification = current_data_truth(db)["data_classification"]
        if (
            active is None
            or active.datasource_id != datasource_id
            or active_relations != expected_relations
            or active_payload.get("data_classification") != expected_classification
        ):
            draft = registry.register(
                scenario_id=scenario_id,
                datasource_id=datasource_id,
                run_id=f"P2B-SQLBOT-BINDING-{scenario_id}",
            )
            registry.approve(draft.binding_release_id)
            active = registry.activate(draft.binding_release_id)
        installed[scenario_id] = active.binding_release_id
    return installed
