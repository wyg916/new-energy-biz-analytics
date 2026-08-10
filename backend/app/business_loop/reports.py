from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.business_loop.common import BusinessLoopError, actor_type_for, record_audit
from app.business_loop.models import (
    Report, ReportEvidenceSnapshot, ReportPublication, ReportReview, ReportVersion,
)
from app.models.auth import User
from app.models.business import AnalysisRun
from app.services.reports import ReportService as DraftReportService


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _loads(value: str):
    return json.loads(value or "{}")


def version_view(row: ReportVersion) -> dict:
    return {
        "report_version_id": row.report_version_id, "report_id": row.report_id,
        "version": row.version, "content": row.content, "summary": row.summary,
        "metric_values": _loads(row.metric_values_json),
        "knowledge_evidence": json.loads(row.knowledge_evidence_json or "[]"),
        "citations": json.loads(row.citations_json or "[]"),
        "created_by": row.created_by, "created_at": row.created_at.isoformat(),
        "dataset_version": row.dataset_version, "semantic_version": row.semantic_version,
        "analysis_run_id": row.analysis_run_id, "run_id": row.run_id,
        "query_plan_hash": row.query_plan_hash, "sql_hash": row.sql_hash,
        "status": row.status, "published_at": row.published_at.isoformat() if row.published_at else None,
    }


class GovernedReportService:
    def __init__(self, db: Session, user: User, *, request_id: str):
        self.db = db
        self.user = user
        self.request_id = request_id

    def _scope(self):
        return [] if not self.user.region_code else [Report.owner == self.user.username]

    def _report(self, report_id: str) -> Report:
        row = self.db.scalar(select(Report).where(Report.report_id == report_id, *self._scope()))
        if row is None:
            raise BusinessLoopError("REPORT_NOT_FOUND", "报告不存在或不在授权范围内", 404)
        return row

    def _version(self, report: Report, version_id: str | None = None) -> ReportVersion:
        target = version_id or report.current_version_id
        row = self.db.get(ReportVersion, target) if target else None
        if row is None or row.report_id != report.report_id:
            raise BusinessLoopError("REPORT_VERSION_NOT_FOUND", "报告版本不存在", 404)
        return row

    def list(self) -> list[dict]:
        rows = self.db.scalars(select(Report).where(*self._scope()).order_by(Report.created_at.desc())).all()
        return [self._view(row) for row in rows]

    def detail(self, report_id: str) -> dict:
        report = self._report(report_id)
        result = self._view(report)
        versions = self.db.scalars(select(ReportVersion).where(
            ReportVersion.report_id == report_id
        ).order_by(ReportVersion.version.desc())).all()
        reviews = self.db.scalars(select(ReportReview).where(
            ReportReview.report_id == report_id
        ).order_by(ReportReview.timestamp.desc())).all()
        result["versions"] = [version_view(row) for row in versions]
        result["reviews"] = [{
            "review_id": row.review_id, "report_version_id": row.report_version_id,
            "status": row.status, "reviewer": row.reviewer, "actor_type": row.actor_type,
            "comment": row.comment, "timestamp": row.timestamp.isoformat(),
        } for row in reviews]
        return result

    def _view(self, row: Report) -> dict:
        version = self._version(row) if row.current_version_id else None
        review = self.db.scalar(select(ReportReview).where(
            ReportReview.report_id == row.report_id
        ).order_by(desc(ReportReview.timestamp)).limit(1))
        publication = self.db.scalar(select(ReportPublication).where(
            ReportPublication.report_id == row.report_id
        ).order_by(desc(ReportPublication.published_at)).limit(1))
        return {
            "report_id": row.report_id, "scenario_id": row.scenario_id, "title": row.title,
            "owner": row.owner, "status": row.status, "created_at": row.created_at.isoformat(),
            "archived_at": row.archived_at.isoformat() if row.archived_at else None,
            "current_version": version_view(version) if version else None,
            "review_status": review.status if review else None,
            "published_at": publication.published_at.isoformat() if publication else None,
        }

    def create(self, *, report_type: str, start: date, end_exclusive: date, title: str | None = None, knowledge_evidence: list | None = None, citations: list | None = None) -> dict:
        draft = DraftReportService(self.db, self.user).draft(report_type, start, end_exclusive)
        run = self.db.get(AnalysisRun, draft["metadata"]["analysis_run_id"])
        if run is None:
            raise BusinessLoopError("REPORT_RUN_MISSING", "报告分析运行记录不存在")
        report_id = f"RPT-{uuid4()}"
        version_id = f"RPV-{uuid4()}"
        report = Report(
            report_id=report_id, scenario_id="charging_ops", title=title or draft["title"],
            owner=self.user.username, status="DRAFT", current_version_id=version_id,
        )
        query_plan_hash = _hash(run.query_plan_json)
        sql_hash = run.sql_hash or _hash(f"deterministic-engine|{run.query_plan_json}")
        version = ReportVersion(
            report_version_id=version_id, report_id=report_id, version=1,
            content=draft["markdown"], summary=f"{report_type} governed report draft",
            metric_values_json=json.dumps(draft["metrics"], ensure_ascii=False, sort_keys=True),
            knowledge_evidence_json=json.dumps(knowledge_evidence or [], ensure_ascii=False),
            citations_json=json.dumps(citations or [], ensure_ascii=False), created_by=self.user.username,
            dataset_version=draft["metadata"].get("dataset_version") or draft["metadata"].get("source_dataset_version") or "unknown",
            semantic_version=draft["metadata"].get("semantic_version") or "0.1.0",
            analysis_run_id=run.run_id, run_id=run.run_id, query_plan_hash=query_plan_hash,
            sql_hash=sql_hash, status="DRAFT",
        )
        self.db.add_all([report, version])
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="report.created",
            resource_type="report", resource_id=report_id, before={},
            after={"report_id": report_id, "version": 1, "status": "DRAFT"},
            reason="governed report draft created", request_id_value=self.request_id, run_id=run.run_id,
        )
        self.db.commit()
        return self.detail(report_id)

    def new_version(self, report_id: str, *, content: str | None, summary: str | None, reason: str) -> dict:
        report = self._report(report_id)
        if report.status == "ARCHIVED":
            raise BusinessLoopError("REPORT_ARCHIVED", "归档报告不能创建新版本")
        current = self._version(report)
        next_number = int(self.db.scalar(select(func.max(ReportVersion.version)).where(
            ReportVersion.report_id == report_id
        )) or 0) + 1
        version = ReportVersion(
            report_version_id=f"RPV-{uuid4()}", report_id=report_id, version=next_number,
            content=content or current.content, summary=summary or current.summary,
            metric_values_json=current.metric_values_json,
            knowledge_evidence_json=current.knowledge_evidence_json, citations_json=current.citations_json,
            created_by=self.user.username, dataset_version=current.dataset_version,
            semantic_version=current.semantic_version, analysis_run_id=current.analysis_run_id,
            run_id=current.run_id, query_plan_hash=current.query_plan_hash, sql_hash=current.sql_hash,
            status="DRAFT",
        )
        before = self._view(report)
        self.db.add(version)
        report.current_version_id = version.report_version_id
        report.status = "VERSIONED"
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="report.new_version",
            resource_type="report", resource_id=report_id, before=before,
            after={"version": next_number, "status": "VERSIONED"}, reason=reason,
            request_id_value=self.request_id, run_id=current.run_id,
        )
        self.db.commit()
        return self.detail(report_id)

    def review(self, report_id: str, *, action: str, reviewer: str, actor_type: str, comment: str) -> dict:
        report = self._report(report_id)
        version = self._version(report)
        if actor_type not in {"HUMAN", "SYSTEM"}:
            raise BusinessLoopError("REVIEW_ACTOR_INVALID", "审核身份类型必须是 HUMAN 或 SYSTEM", 422)
        if actor_type == "SYSTEM" and actor_type_for(reviewer) != "SYSTEM":
            raise BusinessLoopError("SYSTEM_REVIEWER_INVALID", "SYSTEM 审核只能使用受控系统身份", 422)
        before = self._view(report)
        if action == "submit":
            if report.status not in {"DRAFT", "VERSIONED"} or version.status != "DRAFT":
                raise BusinessLoopError("REPORT_STATE_CONFLICT", "当前报告不能提交审核")
            review_status = "SUBMITTED"
            report.status = version.status = "IN_REVIEW"
        elif action == "approve":
            if report.status != "IN_REVIEW" or version.status != "IN_REVIEW":
                raise BusinessLoopError("REPORT_STATE_CONFLICT", "只有审核中的报告可批准")
            review_status = "APPROVED"
            report.status = version.status = "APPROVED"
        elif action == "reject":
            if report.status != "IN_REVIEW" or version.status != "IN_REVIEW":
                raise BusinessLoopError("REPORT_STATE_CONFLICT", "只有审核中的报告可拒绝")
            review_status = "REJECTED"
            report.status = "DRAFT"
            version.status = "DRAFT"
        else:
            raise BusinessLoopError("REVIEW_ACTION_INVALID", "不支持的审核动作", 422)
        review = ReportReview(
            review_id=f"RRV-{uuid4()}", report_id=report_id,
            report_version_id=version.report_version_id, status=review_status,
            reviewer=reviewer, actor_type=actor_type, comment=comment,
        )
        self.db.add(review)
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action=f"report.review_{action}",
            resource_type="report", resource_id=report_id, before=before,
            after={"status": report.status, "review_status": review_status, "reviewer": reviewer, "actor_type": actor_type},
            reason=comment, request_id_value=self.request_id, run_id=version.run_id,
        )
        self.db.commit()
        return self.detail(report_id)

    def publish(self, report_id: str, *, publisher: str, actor_type: str, reason: str) -> dict:
        report = self._report(report_id)
        version = self._version(report)
        if report.status != "APPROVED" or version.status != "APPROVED":
            raise BusinessLoopError("REPORT_NOT_APPROVED", "报告必须先完成批准")
        approved = self.db.scalar(select(ReportReview).where(
            ReportReview.report_version_id == version.report_version_id,
            ReportReview.status == "APPROVED",
        ))
        if approved is None:
            raise BusinessLoopError("REPORT_REVIEW_EVIDENCE_MISSING", "缺少已批准审核记录")
        if actor_type == "SYSTEM" and actor_type_for(publisher) != "SYSTEM":
            raise BusinessLoopError("SYSTEM_PUBLISHER_INVALID", "SYSTEM 发布只能使用受控系统身份", 422)
        generated_at = datetime.now(UTC)
        content_hash = _hash(version.content)
        snapshot_payload = {
            "metric_values": _loads(version.metric_values_json), "query_plan_hash": version.query_plan_hash,
            "sql_hash": version.sql_hash, "dataset_version": version.dataset_version,
            "semantic_version": version.semantic_version, "analysis_run_id": version.analysis_run_id,
            "run_id": version.run_id, "knowledge_evidence": json.loads(version.knowledge_evidence_json),
            "citations": json.loads(version.citations_json), "generated_at": generated_at.isoformat(),
            "content_hash": content_hash,
        }
        snapshot = ReportEvidenceSnapshot(
            snapshot_id=f"RSE-{uuid4()}", report_id=report_id,
            report_version_id=version.report_version_id, metric_values_json=version.metric_values_json,
            query_plan_hash=version.query_plan_hash, sql_hash=version.sql_hash,
            dataset_version=version.dataset_version, semantic_version=version.semantic_version,
            analysis_run_id=version.analysis_run_id, run_id=version.run_id,
            knowledge_evidence_json=version.knowledge_evidence_json, citations_json=version.citations_json,
            generated_at=generated_at, content_hash=content_hash,
            snapshot_hash=_hash(json.dumps(snapshot_payload, ensure_ascii=False, sort_keys=True)),
        )
        publication = ReportPublication(
            publication_id=f"RPB-{uuid4()}", report_id=report_id,
            report_version_id=version.report_version_id, evidence_snapshot_id=snapshot.snapshot_id,
            published_by=publisher, actor_type=actor_type, published_at=generated_at,
        )
        before = self._view(report)
        self.db.add_all([snapshot, publication])
        version.status = "PUBLISHED"
        version.published_at = generated_at
        report.status = "PUBLISHED"
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="report.published",
            resource_type="report", resource_id=report_id, before=before,
            after={"status": "PUBLISHED", "report_version_id": version.report_version_id,
                   "evidence_snapshot_id": snapshot.snapshot_id, "snapshot_hash": snapshot.snapshot_hash},
            reason=reason, request_id_value=self.request_id, run_id=version.run_id,
        )
        self.db.commit()
        return self.detail(report_id)

    def evidence(self, report_id: str) -> dict:
        report = self._report(report_id)
        version = self._version(report)
        snapshot = self.db.scalar(select(ReportEvidenceSnapshot).where(
            ReportEvidenceSnapshot.report_version_id == version.report_version_id
        ))
        if snapshot is None:
            raise BusinessLoopError("REPORT_EVIDENCE_NOT_FROZEN", "当前版本尚未发布，无冻结证据", 404)
        return {
            "snapshot_id": snapshot.snapshot_id, "report_id": snapshot.report_id,
            "report_version_id": snapshot.report_version_id,
            "metric_values": _loads(snapshot.metric_values_json), "query_plan_hash": snapshot.query_plan_hash,
            "sql_hash": snapshot.sql_hash, "dataset_version": snapshot.dataset_version,
            "semantic_version": snapshot.semantic_version, "analysis_run_id": snapshot.analysis_run_id,
            "run_id": snapshot.run_id, "knowledge_evidence": json.loads(snapshot.knowledge_evidence_json),
            "citations": json.loads(snapshot.citations_json), "generated_at": snapshot.generated_at.isoformat(),
            "content_hash": snapshot.content_hash, "snapshot_hash": snapshot.snapshot_hash,
        }

    def archive(self, report_id: str, *, reason: str) -> dict:
        report = self._report(report_id)
        if report.status != "PUBLISHED":
            raise BusinessLoopError("REPORT_NOT_PUBLISHED", "只有已发布报告可归档")
        version = self._version(report)
        before = self._view(report)
        report.status = "ARCHIVED"
        report.archived_at = datetime.now(UTC)
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="report.archived",
            resource_type="report", resource_id=report_id, before=before,
            after={"status": "ARCHIVED", "archived_at": report.archived_at}, reason=reason,
            request_id_value=self.request_id, run_id=version.run_id,
        )
        self.db.commit()
        return self.detail(report_id)
