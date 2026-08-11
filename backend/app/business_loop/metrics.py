from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.business_loop.common import BusinessLoopError, record_audit
from app.business_loop.models import MetricGovernanceVersion
from app.models.auth import User
from app.models.business import MetricDefinition


def _json(value: str, fallback):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def metric_view(row: MetricGovernanceVersion) -> dict:
    return {
        "metric_version_id": row.metric_version_id, "metric_id": row.metric_id,
        "version": row.version, "name": row.name, "business_definition": row.business_definition,
        "formula": row.formula, "unit": row.unit, "dimensions": _json(row.dimensions_json, []),
        "time_grain": row.time_grain, "source_tables": _json(row.source_tables_json, []),
        "owner": row.owner, "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "change_reason": row.change_reason, "impact_analysis": _json(row.impact_analysis_json, {}),
        "status": row.status, "review_outcome": row.review_outcome, "created_by": row.created_by,
        "reviewed_by": row.reviewed_by, "approved_by": row.approved_by,
        "created_at": row.created_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }


class MetricGovernanceService:
    EDITABLE = {
        "name", "business_definition", "formula", "unit", "dimensions",
        "time_grain", "source_tables", "owner", "effective_from", "change_reason",
    }

    def __init__(self, db: Session, user: User, *, request_id: str):
        self.db = db
        self.user = user
        self.request_id = request_id

    def install_catalog_baseline(self) -> int:
        created = 0
        catalog = self.db.scalars(select(MetricDefinition).order_by(MetricDefinition.metric_id)).all()
        for metric in catalog:
            exists = self.db.scalar(select(MetricGovernanceVersion.metric_version_id).where(
                MetricGovernanceVersion.metric_id == metric.metric_id,
                MetricGovernanceVersion.version == metric.version,
            ))
            if exists:
                continue
            grains = _json(metric.supported_grains_json, ["month"])
            self.db.add(MetricGovernanceVersion(
                metric_version_id=f"MGV-{uuid4()}", metric_id=metric.metric_id, version=metric.version,
                name=metric.display_name, business_definition=metric.definition or metric.display_name,
                formula=metric.formula, unit=metric.unit,
                dimensions_json=metric.allowed_dimensions_json or "[]",
                time_grain=grains[0] if grains else "month",
                source_tables_json=metric.source_tables_json or "[]", owner="metric_owner",
                effective_from=date(2025, 1, 1), effective_to=None,
                change_reason="Imported from published semantic layer",
                impact_analysis_json=json.dumps({
                    "baseline_import": True,
                    "checks": ["dashboard", "ChatBI", "diagnostics", "report"],
                }),
                status="PUBLISHED", review_outcome="APPROVED", created_by="system:p6-baseline",
                reviewed_by="system_reviewer", approved_by="system_approver",
                reviewed_at=datetime.now(UTC), approved_at=datetime.now(UTC), published_at=datetime.now(UTC),
            ))
            created += 1
        if created:
            record_audit(
                self.db, actor="quality_agent", actor_type="SYSTEM", action="metric.baseline_imported",
                resource_type="metric_governance", resource_id=None, before={}, after={"created": created},
                reason="published semantic layer synchronized into P6 governance history",
                request_id_value=self.request_id, run_id=f"P6-METRIC-SYNC-{uuid4()}",
            )
            self.db.commit()
        return created

    def list(self) -> list[dict]:
        self.install_catalog_baseline()
        rows = self.db.scalars(select(MetricGovernanceVersion).order_by(
            MetricGovernanceVersion.metric_id, desc(MetricGovernanceVersion.created_at)
        )).all()
        return [metric_view(row) for row in rows]

    def detail(self, metric_id: str) -> dict:
        self.install_catalog_baseline()
        rows = self.db.scalars(select(MetricGovernanceVersion).where(
            MetricGovernanceVersion.metric_id == metric_id
        ).order_by(desc(MetricGovernanceVersion.created_at))).all()
        if not rows:
            raise BusinessLoopError("METRIC_NOT_FOUND", "指标不存在", 404)
        return {"metric_id": metric_id, "versions": [metric_view(row) for row in rows]}

    def _row(self, version_id: str) -> MetricGovernanceVersion:
        row = self.db.get(MetricGovernanceVersion, version_id)
        if row is None:
            raise BusinessLoopError("METRIC_VERSION_NOT_FOUND", "指标版本不存在", 404)
        return row

    def _published(self, metric_id: str) -> MetricGovernanceVersion | None:
        return self.db.scalar(select(MetricGovernanceVersion).where(
            MetricGovernanceVersion.metric_id == metric_id,
            MetricGovernanceVersion.status == "PUBLISHED",
        ).order_by(desc(MetricGovernanceVersion.published_at)).limit(1))

    @staticmethod
    def _next_version(base: str | None) -> str:
        if not base:
            return "0.1.0"
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", base)
        if match:
            major, minor, patch = map(int, match.groups())
            return f"{major}.{minor}.{patch + 1}"
        return f"{base}-p6.1"

    def create_draft(self, payload: dict) -> dict:
        metric_id = str(payload.get("metric_id") or "").strip()
        if not metric_id:
            raise BusinessLoopError("METRIC_ID_REQUIRED", "必须提供 metric_id", 422)
        self.install_catalog_baseline()
        base = self._published(metric_id)
        version = str(payload.get("version") or self._next_version(base.version if base else None))
        if self.db.scalar(select(MetricGovernanceVersion.metric_version_id).where(
            MetricGovernanceVersion.metric_id == metric_id,
            MetricGovernanceVersion.version == version,
        )):
            raise BusinessLoopError("METRIC_VERSION_EXISTS", "该指标版本已存在")
        def value(name: str, default=None):
            if name in payload:
                return payload[name]
            if base is None:
                return default
            mapping = {
                "name": base.name, "business_definition": base.business_definition,
                "formula": base.formula, "unit": base.unit,
                "dimensions": _json(base.dimensions_json, []), "time_grain": base.time_grain,
                "source_tables": _json(base.source_tables_json, []), "owner": base.owner,
                "effective_from": base.effective_from, "change_reason": "",
            }
            return mapping[name]
        required = {name: value(name) for name in ("name", "business_definition", "formula", "unit", "dimensions", "time_grain", "source_tables", "owner", "change_reason")}
        if any(item in (None, "", []) for item in required.values()):
            raise BusinessLoopError("METRIC_DRAFT_INCOMPLETE", "指标草稿缺少必填治理字段", 422)
        effective = value("effective_from") or date.today()
        if isinstance(effective, str):
            effective = date.fromisoformat(effective)
        row = MetricGovernanceVersion(
            metric_version_id=f"MGV-{uuid4()}", metric_id=metric_id, version=version,
            name=required["name"], business_definition=required["business_definition"],
            formula=required["formula"], unit=required["unit"],
            dimensions_json=json.dumps(required["dimensions"], ensure_ascii=False),
            time_grain=required["time_grain"], source_tables_json=json.dumps(required["source_tables"], ensure_ascii=False),
            owner=required["owner"], effective_from=effective, effective_to=None,
            change_reason=required["change_reason"], impact_analysis_json="{}", status="DRAFT",
            created_by=self.user.username,
        )
        self.db.add(row)
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="metric.draft_created",
            resource_type="metric_version", resource_id=row.metric_version_id, before={},
            after={"metric_id": metric_id, "version": version, "status": "DRAFT"},
            reason=row.change_reason, request_id_value=self.request_id, run_id=f"P6-METRIC-{uuid4()}",
        )
        self.db.commit()
        return metric_view(row)

    def update_draft(self, version_id: str, payload: dict, *, reason: str) -> dict:
        row = self._row(version_id)
        if row.status != "DRAFT":
            raise BusinessLoopError("METRIC_IMMUTABLE", "只有 DRAFT 指标版本可修改")
        before = metric_view(row)
        for name, value in payload.items():
            if name not in self.EDITABLE:
                continue
            if name == "dimensions":
                row.dimensions_json = json.dumps(value, ensure_ascii=False)
            elif name == "source_tables":
                row.source_tables_json = json.dumps(value, ensure_ascii=False)
            elif name == "effective_from":
                row.effective_from = date.fromisoformat(value) if isinstance(value, str) else value
            else:
                setattr(row, name, value)
        row.impact_analysis_json = "{}"
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="metric.draft_updated",
            resource_type="metric_version", resource_id=version_id, before=before,
            after=metric_view(row), reason=reason, request_id_value=self.request_id,
            run_id=f"P6-METRIC-{uuid4()}",
        )
        self.db.commit()
        return metric_view(row)

    def impact_analysis(self, version_id: str) -> dict:
        row = self._row(version_id)
        if row.status != "DRAFT":
            raise BusinessLoopError("METRIC_STATE_CONFLICT", "只有 DRAFT 指标版本可执行影响分析")
        base = self._published(row.metric_id)
        comparisons = {
            "formula": base is None or base.formula != row.formula,
            "unit": base is None or base.unit != row.unit,
            "source_tables": base is None or base.source_tables_json != row.source_tables_json,
            "dimensions": base is None or base.dimensions_json != row.dimensions_json,
            "time_grain": base is None or base.time_grain != row.time_grain,
        }
        structural = any(comparisons.values())
        downstream = [
            {"consumer": "dashboard", "checked": True, "affected": structural, "reason": "published metric cards and trends"},
            {"consumer": "ChatBI", "checked": True, "affected": structural, "reason": "deterministic query plan metric binding"},
            {"consumer": "diagnostics", "checked": True, "affected": comparisons["formula"] or comparisons["unit"], "reason": "anomaly and decomposition rules"},
            {"consumer": "report", "checked": True, "affected": structural, "reason": "report evidence snapshots retain metric version"},
        ]
        result = {
            "compared_to_version": base.version if base else None,
            "field_changes": comparisons, "downstream_checks": downstream,
            "impact_level": "HIGH" if comparisons["formula"] or comparisons["source_tables"] else "MEDIUM" if structural else "LOW",
            "checked_at": datetime.now(UTC).isoformat(),
        }
        before = metric_view(row)
        row.impact_analysis_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="metric.impact_analyzed",
            resource_type="metric_version", resource_id=version_id, before=before,
            after={"impact_analysis": result}, reason="mandatory pre-review impact analysis",
            request_id_value=self.request_id, run_id=f"P6-METRIC-{uuid4()}",
        )
        self.db.commit()
        return result

    def review(self, version_id: str, *, action: str, reason: str) -> dict:
        row = self._row(version_id)
        before = metric_view(row)
        now = datetime.now(UTC)
        if action == "submit":
            analysis = _json(row.impact_analysis_json, {})
            if row.status != "DRAFT" or not analysis.get("downstream_checks"):
                raise BusinessLoopError("IMPACT_ANALYSIS_REQUIRED", "提交审核前必须完成结构化影响分析")
            row.status = "REVIEW"
            row.review_outcome = "SUBMITTED"
        elif action == "approve":
            if row.status != "REVIEW":
                raise BusinessLoopError("METRIC_STATE_CONFLICT", "只有 REVIEW 指标可批准")
            row.status = "APPROVED"
            row.review_outcome = "APPROVED"
            row.reviewed_by = row.approved_by = self.user.username
            row.reviewed_at = row.approved_at = now
        elif action == "reject":
            if row.status != "REVIEW":
                raise BusinessLoopError("METRIC_STATE_CONFLICT", "只有 REVIEW 指标可拒绝")
            row.status = "DRAFT"
            row.review_outcome = "REJECTED"
            row.reviewed_by = self.user.username
            row.reviewed_at = now
        else:
            raise BusinessLoopError("METRIC_REVIEW_ACTION_INVALID", "不支持的指标审核动作", 422)
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action=f"metric.review_{action}",
            resource_type="metric_version", resource_id=version_id, before=before,
            after=metric_view(row), reason=reason, request_id_value=self.request_id,
            run_id=f"P6-METRIC-{uuid4()}",
        )
        self.db.commit()
        return metric_view(row)

    def publish(self, version_id: str, *, reason: str) -> dict:
        row = self._row(version_id)
        if row.status != "APPROVED":
            raise BusinessLoopError("METRIC_NOT_APPROVED", "指标版本必须先批准")
        before = metric_view(row)
        now = datetime.now(UTC)
        old = self._published(row.metric_id)
        if old and old.metric_version_id != row.metric_version_id:
            old.status = "DEPRECATED"
            old.effective_to = date.today()
        row.status = "PUBLISHED"
        row.published_at = now
        row.effective_from = row.effective_from or date.today()
        semantic = self.db.get(MetricDefinition, row.metric_id)
        if semantic is None:
            semantic = MetricDefinition(
                metric_id=row.metric_id, display_name=row.name, unit=row.unit, version=row.version,
                status="approved_for_implementation", formula=row.formula,
                allowed_dimensions_json=row.dimensions_json, business_domain="经营分析",
                definition=row.business_definition, source_tables_json=row.source_tables_json,
                supported_grains_json=json.dumps([row.time_grain], ensure_ascii=False), metric_type="aggregation",
            )
            self.db.add(semantic)
        else:
            semantic.display_name = row.name
            semantic.unit = row.unit
            semantic.version = row.version
            semantic.status = "approved_for_implementation"
            semantic.formula = row.formula
            semantic.allowed_dimensions_json = row.dimensions_json
            semantic.definition = row.business_definition
            semantic.source_tables_json = row.source_tables_json
            semantic.supported_grains_json = json.dumps([row.time_grain], ensure_ascii=False)
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="metric.published",
            resource_type="metric_version", resource_id=version_id, before=before,
            after={"current": metric_view(row), "superseded_version_id": old.metric_version_id if old else None},
            reason=reason, request_id_value=self.request_id, run_id=f"P6-METRIC-{uuid4()}",
        )
        self.db.commit()
        return metric_view(row)

    def deprecate(self, version_id: str, *, reason: str) -> dict:
        row = self._row(version_id)
        if row.status != "PUBLISHED":
            raise BusinessLoopError("METRIC_STATE_CONFLICT", "只有 PUBLISHED 指标可停用")
        before = metric_view(row)
        row.status = "DEPRECATED"
        row.effective_to = date.today()
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="metric.deprecated",
            resource_type="metric_version", resource_id=version_id, before=before,
            after=metric_view(row), reason=reason, request_id_value=self.request_id,
            run_id=f"P6-METRIC-{uuid4()}",
        )
        self.db.commit()
        return metric_view(row)
