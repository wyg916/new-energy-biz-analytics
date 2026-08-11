import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.business_loop.alerts import AlertService, ControlledAlertReceiver, alert_state
from app.business_loop.models import (
    AlertEvent, AlertNotificationAttempt, AlertTimelineEvent, BusinessAuditEvent,
    MetricGovernanceVersion, ReportEvidenceSnapshot, ReportVersion,
)
from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data
from app.models.auth import User
from app.models.business import AnalysisRun, MetricDefinition


def _seed() -> None:
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_500)


def test_alert_state_machine_dedup_sla_timeline_notifications_and_audit(client, login) -> None:
    _seed()
    headers = login()
    payload = {
        "metric_id": "charging_revenue", "start": "2026-06-01",
        "end_exclusive": "2026-07-01", "threshold": .0001,
    }
    created = client.post("/api/v1/alerts/generate", headers=headers, json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["created"] is True
    alert = created.json()["alert"]
    assert alert["status"] == "OPEN"
    assert alert["sla_level"] in {"P0", "P1", "P2", "P3"}
    assert alert["sla"]["ack_hours"] > 0 and alert["sla"]["resolve_hours"] > 0
    alert_id = alert["alert_id"]

    repeated = client.post("/api/v1/alerts/generate", headers=headers, json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["deduplicated"] is True
    assert repeated.json()["alert"]["alert_id"] == alert_id

    actions = [
        ("assign", {"reason": "分派验收", "assignee_id": "analyst"}, "ASSIGNED"),
        ("acknowledge", {"reason": "确认预警"}, "ACKNOWLEDGED"),
        ("in-progress", {"reason": "开始处置"}, "IN_PROGRESS"),
        ("resolve", {"reason": "完成处置", "summary": "已核对指标口径与经营数据"}, "RESOLVED"),
        ("verify", {"reason": "验证结果", "summary": "质量复核通过"}, "VERIFIED"),
        ("close", {"reason": "关闭预警"}, "CLOSED"),
        ("reopen", {"reason": "复查发现需继续跟进"}, "REOPENED"),
    ]
    for endpoint, body, expected in actions:
        response = client.post(f"/api/v1/alerts/{alert_id}/{endpoint}", headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == expected

    commented = client.post(f"/api/v1/alerts/{alert_id}/comments", headers=headers, json={"reason": "补充复查说明"})
    assert commented.status_code == 200

    timeline = client.get(f"/api/v1/alerts/{alert_id}/timeline", headers=headers)
    assert timeline.status_code == 200
    assert [item["after_state"] for item in timeline.json()["rows"]] == [
        "OPEN", "ASSIGNED", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "VERIFIED", "CLOSED", "REOPENED",
        "REOPENED",
    ]
    assert timeline.json()["rows"][-1]["event_type"] == "commented"
    detail = client.get(f"/api/v1/alerts/{alert_id}", headers=headers).json()
    assert detail["notification_attempts"][-1]["status"] == "ACKNOWLEDGED"
    with SessionLocal() as db:
        assert len(db.scalars(select(AlertEvent)).all()) == 1
        assert len(db.scalars(select(AlertTimelineEvent)).all()) == 9
        assert db.scalar(select(BusinessAuditEvent).where(BusinessAuditEvent.action == "alert.reopen"))


def test_alert_retry_failure_audit_and_overdue_projection(client, login) -> None:
    _seed()
    login()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "analyst"))
        service = AlertService(
            db, user, request_id="REQ-P6-RETRY",
            receiver=ControlledAlertReceiver(["FAILED", "ACKNOWLEDGED"]),
        )
        result = service.generate(
            metric_id="gross_profit", start=date(2026, 5, 1),
            end_exclusive=date(2026, 6, 1), threshold=.0001,
        )
        assert result["created"] is True
        attempts = db.scalars(select(AlertNotificationAttempt).where(
            AlertNotificationAttempt.alert_id == result["alert"]["alert_id"]
        ).order_by(AlertNotificationAttempt.attempt_no)).all()
        assert [item.status for item in attempts] == ["FAILED", "ACKNOWLEDGED"]
        failure = db.scalar(select(BusinessAuditEvent).where(
            BusinessAuditEvent.resource_id == attempts[0].notification_id
        ))
        assert failure and failure.outcome == "FAILED"

        overdue = AlertEvent(
            alert_id="ALT-OVERDUE", scenario_id="charging_ops", metric_id="gross_profit",
            entity_type="PORTFOLIO", entity_id="ALL", severity="P0", title="overdue", description="test",
            current_value=Decimal("2"), baseline_value=Decimal("1"), change_rate=Decimal("1"),
            rule_id="test", rule_version="1", analysis_period_start=date(2026, 1, 1),
            analysis_period_end=date(2026, 2, 1), deduplication_key="overdue-key",
            analysis_run_id="RUN-OVERDUE", run_id="RUN-OVERDUE", status="OPEN",
            sla_level="P0", ack_due_at=datetime.now(UTC) - timedelta(hours=2),
            due_at=datetime.now(UTC) - timedelta(hours=1), escalation_status="NONE",
            dataset_version="test", semantic_version="0.1.0", evidence_json="{}",
        )
        db.add(overdue)
        db.commit()
        view = alert_state(overdue)
        assert view["overdue"] is True
        assert view["escalation_status"] == "RESOLVE_OVERDUE"


def test_alert_rbac_is_enforced_server_side(client, login) -> None:
    _seed()
    admin_headers = login()
    created = client.post("/api/v1/alerts/generate", headers=admin_headers, json={
        "metric_id": "gross_profit", "start": "2026-06-01",
        "end_exclusive": "2026-07-01", "threshold": .0001,
    })
    assert created.status_code == 200
    alert_id = created.json()["alert"]["alert_id"]
    viewer_headers = login("executive", "AlphaExec!2026")
    assert client.get("/api/v1/alerts", headers=viewer_headers).status_code == 200
    denied = client.post(f"/api/v1/alerts/{alert_id}/acknowledge", headers=viewer_headers, json={"reason": "越权尝试"})
    assert denied.status_code == 403
    with SessionLocal() as db:
        audit = db.scalar(select(BusinessAuditEvent).where(BusinessAuditEvent.outcome == "DENIED"))
        assert audit and audit.actor == "executive"


def test_report_version_review_immutable_evidence_publish_and_archive(client, login) -> None:
    _seed()
    headers = login()
    created = client.post("/api/v1/reports", headers=headers, json={
        "report_type": "monthly", "start": "2026-06-01", "end_exclusive": "2026-07-01",
        "title": "P6 经营月报", "knowledge_evidence": [{
            "document_id": "DOC-1", "document_version_id": "DV-1", "chunk_id": "CHK-1",
            "title": "指标口径", "page": 1, "section": "经营", "paragraph_start": 1,
            "paragraph_end": 2, "locator": "docs/metric#p1",
        }], "citations": [{"document_id": "DOC-1", "locator": "docs/metric#p1"}],
    })
    assert created.status_code == 200, created.text
    report_id = created.json()["report_id"]
    versioned = client.post(f"/api/v1/reports/{report_id}/versions", headers=headers, json={
        "reason": "补充经营摘要", "summary": "P6 reviewed monthly report",
    })
    assert versioned.status_code == 200
    assert versioned.json()["current_version"]["version"] == 2
    submitted = client.post(f"/api/v1/reports/{report_id}/submit-review", headers=headers, json={
        "reviewer": "system_reviewer", "actor_type": "SYSTEM", "comment": "自动化流程提交",
    })
    assert submitted.status_code == 200 and submitted.json()["status"] == "IN_REVIEW"
    approved = client.post(f"/api/v1/reports/{report_id}/approve", headers=headers, json={
        "reviewer": "system_reviewer", "actor_type": "SYSTEM", "comment": "结构与证据检查通过",
    })
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    published = client.post(f"/api/v1/reports/{report_id}/publish", headers=headers, json={
        "publisher": "system_approver", "actor_type": "SYSTEM", "reason": "本地集成验收发布",
    })
    assert published.status_code == 200 and published.json()["status"] == "PUBLISHED"
    evidence = client.get(f"/api/v1/reports/{report_id}/evidence", headers=headers)
    assert evidence.status_code == 200
    frozen = evidence.json()
    assert frozen["metric_values"] and frozen["query_plan_hash"] and frozen["sql_hash"]
    assert frozen["knowledge_evidence"][0]["document_id"] == "DOC-1"
    assert frozen["content_hash"] and frozen["snapshot_hash"]

    archived = client.post(f"/api/v1/reports/{report_id}/archive", headers=headers, json={"reason": "周期结束归档"})
    assert archived.status_code == 200 and archived.json()["status"] == "ARCHIVED"
    with SessionLocal() as db:
        version = db.scalar(select(ReportVersion).where(ReportVersion.report_id == report_id, ReportVersion.status == "PUBLISHED"))
        version.content = "forbidden mutation"
        with pytest.raises(ValueError, match="immutable"):
            db.commit()
        db.rollback()
        snapshot = db.scalar(select(ReportEvidenceSnapshot).where(ReportEvidenceSnapshot.report_id == report_id))
        snapshot.metric_values_json = "{}"
        with pytest.raises(ValueError, match="immutable"):
            db.commit()
        db.rollback()


def test_report_reject_and_rbac_negative(client, login) -> None:
    _seed()
    admin = login()
    report = client.post("/api/v1/reports", headers=admin, json={
        "report_type": "weekly", "start": "2026-06-01", "end_exclusive": "2026-06-08",
    }).json()
    report_id = report["report_id"]
    client.post(f"/api/v1/reports/{report_id}/submit-review", headers=admin, json={"comment": "提交审核"})
    rejected = client.post(f"/api/v1/reports/{report_id}/reject", headers=admin, json={"comment": "证据说明不足"})
    assert rejected.status_code == 200 and rejected.json()["status"] == "DRAFT"
    regional = login("regional", "AlphaRegion!2026")
    assert client.post(f"/api/v1/reports/{report_id}/approve", headers=regional, json={"comment": "越权批准"}).status_code == 403


def test_metric_governance_versioning_impact_publish_traceability_and_rbac(client, login) -> None:
    _seed()
    headers = login()
    catalog = client.get("/api/v1/metrics/governance", headers=headers)
    assert catalog.status_code == 200
    assert len({row["metric_id"] for row in catalog.json()["rows"]}) == 15
    old = next(row for row in catalog.json()["rows"] if row["metric_id"] == "charging_revenue" and row["status"] == "PUBLISHED")
    draft = client.post("/api/v1/metrics/governance/drafts", headers=headers, json={
        "metric_id": "charging_revenue", "formula": "SUM(electricity_fee_net_amount + service_fee_net_amount)",
        "change_reason": "明确已完成订单口径并执行影响分析",
    })
    assert draft.status_code == 200, draft.text
    version_id = draft.json()["metric_version_id"]
    impact = client.post(f"/api/v1/metrics/governance/versions/{version_id}/impact-analysis", headers=headers)
    assert impact.status_code == 200
    assert impact.json()["field_changes"]["formula"] is True
    assert {item["consumer"] for item in impact.json()["downstream_checks"]} == {"dashboard", "ChatBI", "diagnostics", "report"}
    submitted = client.post(f"/api/v1/metrics/governance/versions/{version_id}/submit-review", headers=headers, json={"reason": "影响分析完成"})
    assert submitted.status_code == 200 and submitted.json()["status"] == "REVIEW"
    approved = client.post(f"/api/v1/metrics/governance/versions/{version_id}/approve", headers=headers, json={"reason": "指标负责人批准"})
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    published = client.post(f"/api/v1/metrics/governance/versions/{version_id}/publish", headers=headers, json={"reason": "发布新指标版本"})
    assert published.status_code == 200 and published.json()["status"] == "PUBLISHED"
    with SessionLocal() as db:
        old_row = db.get(MetricGovernanceVersion, old["metric_version_id"])
        assert old_row.status == "DEPRECATED"
        semantic = db.get(MetricDefinition, "charging_revenue")
        assert semantic.version == published.json()["version"]
        run = db.scalar(select(AnalysisRun).order_by(AnalysisRun.created_at).limit(1))
        if run:
            versions = json.loads(run.metric_versions_json)
            assert versions.get("charging_revenue") == "0.1.0"
    regional = login("regional", "AlphaRegion!2026")
    denied = client.post("/api/v1/metrics/governance/drafts", headers=regional, json={
        "metric_id": "gross_profit", "change_reason": "越权创建",
    })
    assert denied.status_code == 403
    audit = client.get("/api/v1/business-audit", headers=headers)
    assert audit.status_code == 200
    assert any(row["action"] == "metric.published" for row in audit.json()["rows"])
