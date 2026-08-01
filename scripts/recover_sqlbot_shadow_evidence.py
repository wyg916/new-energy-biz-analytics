"""Recover SQLBot ChatRecord telemetry for an already executed Shadow batch.

Input is a JSON array exported read-only from the SQLBot database. The script
updates only the matching platform Shadow rows and the acceptance JSON artifact.
It never persists model prose, result rows, credentials, or session tokens.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.chatbi.guard import QueryRejected, guard_sqlbot_sql
from app.core.database import SessionLocal
from app.models.auth import User
from app.models.query_routing import SQLBotSessionBindingRecord, ShadowEvaluation
from app.query_engines.context import build_query_context
from app.scenarios.charging_ops.runtime import resolve_charging_ops_context
from app.scenarios.sales_ops.runtime import resolve_sales_ops_context


DATASOURCE_IDS = {"charging_ops": "1", "sales_ops": "2"}


def _sha256(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest() if value else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    records = json.load(sys.stdin)
    if not isinstance(records, list) or len(records) != 20:
        raise RuntimeError("recovery input must contain exactly 20 ChatRecords")
    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    by_trace = {str(item["trace_id"]): item for item in artifact["results"]}

    recovered_sql = 0
    recovered_tokens = 0
    recovered_latency = 0
    recovered_rows: list[str] = []
    with SessionLocal() as db:
        user = db.scalar(
            select(User)
            .where(User.is_active.is_(True))
            .order_by((User.role == "analyst_admin").desc(), User.id)
        )
        if user is None:
            raise RuntimeError("no active acceptance user")
        _, charging_active = resolve_charging_ops_context(db, user)
        _, sales_active = resolve_sales_ops_context(db, user)
        active = {
            "charging_ops": charging_active,
            "sales_ops": sales_active,
        }

        for source in records:
            chat_id = str(source["chat_id"])
            binding = db.scalar(
                select(SQLBotSessionBindingRecord).where(
                    SQLBotSessionBindingRecord.external_chat_id == chat_id,
                    SQLBotSessionBindingRecord.conversation_id.like("p2a-shadow-%"),
                )
            )
            if binding is None:
                raise RuntimeError(f"no platform binding for SQLBot chat {chat_id}")
            shadow = db.scalar(
                select(ShadowEvaluation).where(
                    ShadowEvaluation.conversation_id == binding.conversation_id,
                    ShadowEvaluation.scenario == binding.scenario_id,
                    ShadowEvaluation.trace_id.like("P2A-SHADOW-%"),
                )
            )
            if shadow is None:
                raise RuntimeError(f"no Shadow row for SQLBot chat {chat_id}")
            item = by_trace.get(shadow.trace_id)
            if item is None:
                raise RuntimeError(f"artifact has no trace {shadow.trace_id}")

            token_usage = source.get("token_usage")
            if isinstance(token_usage, int):
                shadow.token_usage = token_usage
                item["sqlbot_token_usage"] = token_usage
                recovered_tokens += 1
            duration_ms = source.get("duration_ms")
            if isinstance(duration_ms, int) and duration_ms >= 0:
                shadow.latency_ms = duration_ms
                item["sqlbot_latency_ms"] = duration_ms
                recovered_latency += 1
            sql = source.get("sql")
            if isinstance(sql, str) and sql.strip():
                context = replace(
                    build_query_context(
                        db,
                        conversation_id=binding.conversation_id,
                        platform_context=active[binding.scenario_id],
                    ),
                    datasource_id=DATASOURCE_IDS[binding.scenario_id],
                    max_rows=500,
                )
                shadow.sqlbot_sql = sql
                item["sqlbot_generated_sql"] = sql
                item["sqlbot_sql_hash"] = _sha256(sql)
                try:
                    guard_sqlbot_sql(sql, context)
                except QueryRejected as exc:
                    shadow.permission_result = "REJECTED"
                    shadow.error_code = "QUERY_GUARD_REJECTED"
                    shadow.error = str(exc)
                    item["permission_result"] = "REJECTED"
                    item["error_code"] = "QUERY_GUARD_REJECTED"
                else:
                    shadow.permission_result = "PASS"
                    item["permission_result"] = "PASS"
                recovered_sql += 1
            item["sqlbot_chat_id"] = chat_id
            item["sqlbot_record_id"] = str(source["record_id"])
            item["trace_recovered_from_sqlbot_chat_record"] = True
            recovered_rows.append(shadow.shadow_evaluation_id)
        db.commit()

    if len(set(recovered_rows)) != 20:
        raise RuntimeError("recovery did not map to 20 unique Shadow rows")
    artifact["runtime_status"] = "COMPLETED_WITH_FAILURES"
    artifact["sql_generated_count"] = recovered_sql
    artifact["token_observed_count"] = recovered_tokens
    artifact["latency_observed_count"] = recovered_latency
    artifact["guard_pass_count"] = sum(
        item["permission_result"] == "PASS" for item in artifact["results"]
    )
    artifact["guard_rejected_count"] = sum(
        item["permission_result"] == "REJECTED" for item in artifact["results"]
    )
    artifact["evidence_recovered_from_sqlbot_chat_records"] = True
    artifact["reconstructed_trace_count"] = 20
    args.artifact.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "recovered_rows": len(recovered_rows),
        "sql_generated": recovered_sql,
        "token_observed": recovered_tokens,
        "latency_observed": recovered_latency,
    }))


if __name__ == "__main__":
    main()
