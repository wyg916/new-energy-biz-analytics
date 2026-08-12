"""Build fail-closed DAY-1 capability and bug-closure evidence.

This script joins browser workflow evidence, a one-click startup report, and
the isolated backend regression summary.  It never treats registration,
readiness, or row counts as a substitute for a user-visible workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid JSON evidence {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"JSON evidence must be an object: {path}")
    return value


def artifact(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        relative = str(path.resolve())
    return {
        "path": relative,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def step_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id") or item.get("name")): item
        for item in payload.get("steps", [])
        if isinstance(item, dict) and (item.get("id") or item.get("name"))
    }


def passed_step(steps: dict[str, dict[str, Any]], name: str) -> bool:
    return str(steps.get(name, {}).get("status", "")).upper() in {
        "PASS", "BOUNDARY_PASS"
    }


def api_count(payload: dict[str, Any], fragment: str, method: str | None = None) -> int:
    return sum(
        1
        for item in payload.get("api_responses", [])
        if isinstance(item, dict)
        and fragment in str(item.get("url") or "")
        and (method is None or item.get("method") == method)
        and item.get("ok") is True
    )


def parse_gateway_probe(startup_steps: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw = startup_steps.get("Runtime ModelGateway provider calls", {}).get("detail")
    if not isinstance(raw, str):
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def decision(ok: bool, reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "PASS" if ok else "FAIL", "reason": reason, **extra}


def bug(
    bug_id: str,
    title: str,
    kind: str,
    resolution: str,
    verification: list[str],
    closed: bool,
) -> dict[str, Any]:
    return {
        "id": bug_id,
        "priority": "P1",
        "kind": kind,
        "title": title,
        "status": "BUG_FIXED_PASS" if closed else "OPEN",
        "resolution": resolution,
        "verification": verification,
    }


def build(
    functional_path: Path,
    second_path: Path,
    startup_path: Path,
    backend_path: Path,
) -> dict[str, Any]:
    functional = read_json(functional_path)
    second = read_json(second_path)
    startup = read_json(startup_path)
    backend = read_json(backend_path)
    functional_steps = step_map(functional)
    startup_steps = step_map(startup)

    browser_clean = all(
        not functional.get(key)
        for key in ("console_errors", "page_errors", "request_failures")
    ) and all(
        isinstance(item, dict) and item.get("ok") is True
        for item in functional.get("api_responses", [])
    )
    second_clean = (
        second.get("status") == "PASS"
        and all(not second.get(key) for key in (
            "console_errors", "page_errors", "request_failures", "blocking_responses"
        ))
    )

    chatbi_ok = (
        passed_step(functional_steps, "CHATBI-001")
        and passed_step(functional_steps, "CHATBI-002")
        and api_count(functional, "/api/v1/assistant/query", "POST") >= 4
        and api_count(functional, "/api/v1/assistant/feedback", "POST") >= 1
        and api_count(functional, "/api/v1/chat/sessions/", "DELETE") >= 1
    )
    diagnostics_ok = (
        passed_step(functional_steps, "DASHBOARD-001")
        and passed_step(functional_steps, "MARGIN-001")
        and api_count(functional, "/api/v1/diagnostics/decomposition", "GET") >= 3
    )
    rag_ok = (
        passed_step(functional_steps, "KNOWLEDGE-001")
        and api_count(functional, "/api/v1/knowledge/retrieval/test", "POST") >= 1
        and api_count(functional, "/api/v1/knowledge/documents/ingest", "POST") >= 1
        and passed_step(startup_steps, "RAG rebuild and index completeness")
    )
    memory_ok = (
        passed_step(functional_steps, "MEMORY-001")
        and api_count(functional, "/api/v1/memory/export", "GET") >= 1
        and api_count(functional, "/api/v1/memory/records/", "DELETE") >= 1
        and passed_step(startup_steps, "Memory scheduler and Integration runtime")
    )
    p6_steps = ("P6-ALERT-001", "P6-REPORT-001", "P6-METRIC-001")
    p6_ok = all(passed_step(functional_steps, item) for item in p6_steps)
    p6_api_ok = all(
        api_count(functional, fragment) > 0
        for fragment in ("/api/v1/alerts", "/api/v1/reports", "/api/v1/metrics/governance")
    )

    probe = parse_gateway_probe(startup_steps)
    provider_rows = {
        str(item.get("provider")): item
        for item in probe.get("providers", [])
        if isinstance(item, dict) and item.get("provider")
    }
    provider_decisions: dict[str, dict[str, Any]] = {}
    for provider in ("kimi", "mimo", "deepseek"):
        row = provider_rows.get(provider, {})
        ok = (
            startup.get("status") == "PASS"
            and passed_step(startup_steps, "Runtime ModelGateway provider calls")
            and row.get("status") == "PASS"
            and row.get("response_valid") is True
        )
        provider_decisions[provider] = decision(
            ok,
            "one-click runtime ModelGateway call returned a schema-valid response",
            model=row.get("model"),
            latency_ms=row.get("latency_ms"),
            response_content_exposed=False,
        )
    runtime = startup.get("runtime") if isinstance(startup.get("runtime"), dict) else {}
    sqlbot_ok = (
        passed_step(startup_steps, "SQLBot readonly roles and Source Bindings")
        and runtime.get("sqlbot_provider_registration") == "PASS"
        and runtime.get("sqlbot_open_nl2sql_eligible") is False
        and runtime.get("sqlbot_traffic_enabled") is False
        and runtime.get("query_engine_mode") == "DETERMINISTIC_ONLY"
    )
    sqlbot = {
        "status": "AVAILABLE" if sqlbot_ok else "FAIL",
        "reason": (
            "registered with readonly scenario bindings; open NL2SQL engine is not eligible "
            "under the frozen Full Integration contract, traffic remains disabled, and the "
            "user-visible deterministic fallback was exercised"
        ),
        "registered": sqlbot_ok,
        "user_visible_engine_offered": False,
        "traffic_enabled": False,
    }

    counts = backend.get("counts") if isinstance(backend.get("counts"), dict) else {}
    backend_ok = (
        backend.get("status") == "PASS"
        and int(counts.get("tests") or 0) > 0
        and all(int(counts.get(key) or 0) == 0 for key in ("failures", "errors", "skipped"))
        and backend.get("main_database_modified") is False
        and backend.get("temporary_containers_removed") is True
    )

    common_ok = functional.get("status") == "PASS" and browser_clean and second_clean
    bugs = [
        bug("DAY1-BUG-001", "验收脚本误点击冻结禁用控件", "acceptance_harness",
            "按产品边界改为验证 disabled 与非空原因，不触发不可用动作。",
            ["day1-functional-playwright.second-pass.json:interaction_results"], common_ok),
        bug("DAY1-BUG-002", "设备故障帕累托无事件时被误判失败", "acceptance_harness",
            "同时校验 API reason_summary 为空与用户可见空状态。",
            ["DEVICES-001"], passed_step(functional_steps, "DEVICES-001")),
        bug("DAY1-BUG-003", "销售中文日范围解析与推荐问题越过活动数据窗口", "product_backend",
            "支持中文日级闭区间并转成右开区间；推荐问题由活动数据范围动态生成。",
            ["CHATBI-001", "backend full regression"], chatbi_ok and backend_ok),
        bug("DAY1-BUG-004", "长合法幂等键导致质量 run_id 超长且来源写死为模拟", "product_backend",
            "质量 run_id 使用 SHA-256 摘要，并从当前数据事实读取分类、版本和 run_id。",
            ["MAPPING-002", "backend full regression"], passed_step(functional_steps, "MAPPING-002") and backend_ok),
        bug("DAY1-BUG-005", "回滚幂等键超过 API 长度上限", "product_frontend",
            "使用当前版本与目标版本构造受限长度稳定幂等键。",
            ["MAPPING-002"], passed_step(functional_steps, "MAPPING-002")),
        bug("DAY1-BUG-006", "同日期再次建版本复用了旧幂等结果", "product_frontend",
            "幂等键加入下一版本号，重复验收仍创建唯一 DatasetVersion。",
            ["MAPPING-002"], passed_step(functional_steps, "MAPPING-002")),
        bug("DAY1-BUG-007", "字段映射成功反馈在用户读完前自动消失", "product_frontend",
            "成功与失败反馈保留到下一次用户动作。",
            ["MAPPING-001", "MAPPING-002"], passed_step(functional_steps, "MAPPING-001") and passed_step(functional_steps, "MAPPING-002")),
        bug("DAY1-BUG-008", "治理页标题前缀导致导航验收误判", "acceptance_harness",
            "导航校验采用可见标题包含关系，同时保留精确侧栏入口。",
            ["GOVERNANCE-001"], passed_step(functional_steps, "GOVERNANCE-001")),
        bug("DAY1-BUG-009", "页面盘点在全局数据状态尚未完成时采样", "acceptance_harness",
            "每个认证页面等待统一数据状态完成后再采集截图与契约字段。",
            ["day1-functional-playwright.second-pass.json:frontend_data_label_scan"], second_clean),
        bug("DAY1-BUG-010", "重复一键启动的 P6 E2E 假定预警初态固定为 OPEN", "acceptance_harness",
            "读取持久库当前预警状态，按服务端状态机完成包含重开的幂等闭环并回到 CLOSED。",
            ["one-click startup:P6 frontend E2E", "second startup:P6 frontend E2E"],
            passed_step(startup_steps, "P6 frontend E2E")),
    ]

    chatbi_audit = decision(chatbi_ok and browser_clean,
        "multi-scenario, multi-turn, answer/query guard, feedback and server-side new-session flows passed",
        passed_steps=["CHATBI-001", "CHATBI-002"],
        successful_assistant_queries=api_count(functional, "/api/v1/assistant/query", "POST"))
    rag_audit = decision(rag_ok and browser_clean,
        "retrieval citations plus ingest/publish/retire UI lifecycle and runtime index completeness passed")
    memory_audit = decision(memory_ok and browser_clean,
        "working-memory read, confirmed write, parsed JSON download, delete verification and scheduler passed")
    p6_audit = decision(p6_ok and p6_api_ok and browser_clean,
        "alert, report and metric-governance user-visible state-machine lifecycles passed",
        passed_steps=list(p6_steps))
    model_provider_audit = decision(
        sqlbot_ok and all(item["status"] == "PASS" for item in provider_decisions.values()),
        "three governed ModelGateway providers were called; SQLBot frozen eligibility boundary was verified",
        gates={"sqlbot": sqlbot, **provider_decisions},
        providers={"sqlbot": sqlbot, **provider_decisions},
        secret_values_exposed=False,
    )

    all_ok = all(item["status"] == "PASS" for item in (
        chatbi_audit, rag_audit, memory_audit, p6_audit, model_provider_audit
    )) and diagnostics_ok and backend_ok and all(item["status"] == "BUG_FIXED_PASS" for item in bugs)
    return {
        "schema_version": "1.0",
        "evidence_type": "day1_supplemental_capability_audits",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if all_ok else "FAIL",
        "chatbi_audit": chatbi_audit,
        "model_provider_audit": model_provider_audit,
        "rag_audit": rag_audit,
        "memory_audit": memory_audit,
        "p6_audit": p6_audit,
        "gates": {
            "CHATBI": chatbi_audit,
            "SQLBOT": sqlbot,
            "KIMI": provider_decisions["kimi"],
            "MIMO": provider_decisions["mimo"],
            "DEEPSEEK": provider_decisions["deepseek"],
            "RAG": rag_audit,
            "MEMORY": memory_audit,
            "DIAGNOSTICS": decision(diagnostics_ok, "dashboard and margin diagnostics API workflows passed"),
            "ALERT": decision(passed_step(functional_steps, "P6-ALERT-001") and p6_api_ok, "alert lifecycle passed"),
            "REPORT": decision(passed_step(functional_steps, "P6-REPORT-001") and p6_api_ok, "report lifecycle passed"),
            "METRIC_GOVERNANCE": decision(passed_step(functional_steps, "P6-METRIC-001") and p6_api_ok, "metric governance lifecycle passed"),
            "BACKEND_REGRESSION": decision(backend_ok, f"isolated PostgreSQL regression: {counts}"),
        },
        "bugs": bugs,
        "source_artifacts": [
            artifact(functional_path), artifact(second_path), artifact(startup_path), artifact(backend_path)
        ],
        "secret_values_exposed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--functional", type=Path, required=True)
    parser.add_argument("--second-pass", type=Path, required=True)
    parser.add_argument("--startup", type=Path, required=True)
    parser.add_argument("--backend-regression", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    paths = [args.functional, args.second_pass, args.startup, args.backend_regression]
    resolved = [path if path.is_absolute() else ROOT / path for path in paths]
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if output.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite evidence without --force: {output}")
    result = build(*resolved)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"status": result["status"], "output": str(output), "bug_count": len(result["bugs"])}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
