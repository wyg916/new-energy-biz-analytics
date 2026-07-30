import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import AuditLog, User
from app.models.business import AnalysisRun, DataGenerationRun
from app.services.dashboard import allowed_station_ids
from app.services.diagnostics import DiagnosticService
from app.services.metric_catalog import METRICS
from app.scenarios.registry import published_charging_ops_batch
from app.services.metrics import MetricService
from app.core.config import get_settings
from app.scenarios.charging_ops.runtime import (
    platform_version_metadata,
    resolve_charging_ops_context,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _display_value(metric_id: str, value):
    if value is None:
        return "数据不足"
    if metric_id in {"gross_margin", "station_utilization_rate", "device_online_rate", "device_fault_rate"}:
        return round(value * 100, 4)
    return value


class ReportService:
    def __init__(self, db: Session, user: User):
        self.db = db; self.user = user
        self.platform_context = (
            resolve_charging_ops_context(db, user)[1]
            if get_settings().platform_version_routing_enabled
            else None
        )

    def draft(self, report_type: str, start: date, end_exclusive: date) -> dict:
        if report_type not in {"weekly", "monthly"}:
            raise ValueError("report_type must be weekly or monthly")
        station_ids = allowed_station_ids(self.db, self.user)
        metrics = MetricService(self.db).compute(list(METRICS), start, end_exclusive, station_ids)
        diagnostic = DiagnosticService(self.db, self.user).decompose("gross_profit", start, end_exclusive, "mom", 5)
        run_id = f"REPORT-{uuid4()}"
        batch = published_charging_ops_batch(self.db)
        title = f"新能源经营分析{'周报' if report_type == 'weekly' else '月报'}草稿"
        lines = [f"# {title}", "", "> 模拟数据 · 可审核草稿 · 不代表真实企业经营结论", "", f"数据时间：{start.isoformat()} 至 {end_exclusive.isoformat()}（右开）", f"来源：平台数据库 / 批次 {batch.batch_id if batch else '无可用批次'}", f"analysis_run_id：{run_id}", "", "## 核心指标", "", "| 指标 | 值 | 单位 |", "|---|---:|---|"]
        if self.platform_context:
            lines[7:7] = [
                f"scenario_version：{self.platform_context.scenario_version}",
                f"semantic_version：{self.platform_context.semantic_version}",
                f"dataset_version：{self.platform_context.dataset_version}",
            ]
        for metric_id, value in metrics.items():
            lines.append(f"| {METRICS[metric_id][0]} | {_display_value(metric_id, value)} | {METRICS[metric_id][1]} |")
        lines.extend(["", "## 毛利变化拆解", ""])
        for item in diagnostic["bridge"]:
            lines.append(f"- {item['driver']}：{item['contribution']} 元")
        lines.extend(["", "## 重点场站贡献", ""])
        for item in diagnostic["station_contributions"]:
            lines.append(f"- {item['station_name']}（{item['region_id']}）：{item['contribution']} 元")
        lines.extend(["", "## 解释边界", "", "设备在线率、故障率等因素仅作为同期关联线索，不构成因果结论。报告仅引用结构化计算结果，可通过 run_id、批次和指标版本回溯。"])
        markdown = "\n".join(lines) + "\n"
        now = datetime.now(UTC)
        plan = {"kind": "report_draft", "report_type": report_type, "start": start.isoformat(), "end_exclusive": end_exclusive.isoformat(), "metric_ids": list(METRICS)}
        run = AnalysisRun(run_id=run_id, request_id=f"REQ-{uuid4()}", conversation_id=f"REPORT-{uuid4()}", user_id=self.user.id, role_id=self.user.role, allowed_region_ids=json.dumps([self.user.region_code] if self.user.region_code else ["R01", "R02", "R03"]), question=title, query_plan_json=json.dumps(plan), query_plan_version="report-0.1.0", params_redacted_json=json.dumps({"station_count": len(station_ids)}), metric_versions_json=json.dumps({key: "0.1.0" for key in METRICS}), batch_id=batch.batch_id if batch else None, status="succeeded", row_count=len(metrics), duration_ms=0, result_digest=_digest(json.dumps(metrics, sort_keys=True)), answer_digest=_digest(markdown), created_at=now, finished_at=now)
        self.db.add(run)
        self.db.add(AuditLog(actor_user_id=self.user.id, action="report.draft", resource="report_draft", outcome="success", detail_json=json.dumps({"analysis_run_id": run_id, "report_type": report_type})))
        self.db.commit()
        metadata = {"analysis_run_id": run_id, "data_classification": "simulated", "data_time_range": {"start": start.isoformat(), "end_exclusive": end_exclusive.isoformat()}, "source": "platform_database", "batch_id": batch.batch_id if batch else None, "metric_versions": {key: "0.1.0" for key in METRICS}, "status": "draft"}
        if self.platform_context:
            metadata.update(platform_version_metadata(self.platform_context))
        return {"title": title, "report_type": report_type, "metrics": metrics, "diagnostic": diagnostic, "markdown": markdown, "metadata": metadata}

    @staticmethod
    def csv_bytes(report: dict) -> bytes:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["data_classification", "simulated"])
        writer.writerow(["analysis_run_id", report["metadata"]["analysis_run_id"]])
        writer.writerow(["source", report["metadata"]["source"]])
        writer.writerow(["batch_id", report["metadata"]["batch_id"]])
        writer.writerow(["scenario_version", report["metadata"].get("scenario_version")])
        writer.writerow(["semantic_version", report["metadata"].get("semantic_version")])
        writer.writerow(["dataset_version", report["metadata"].get("dataset_version")])
        writer.writerow(["metric_id", "metric_name", "value", "unit", "metric_version"])
        for metric_id, value in report["metrics"].items():
            writer.writerow([metric_id, METRICS[metric_id][0], _display_value(metric_id, value), METRICS[metric_id][1], "0.1.0"])
        return ("\ufeff" + output.getvalue()).encode("utf-8")
