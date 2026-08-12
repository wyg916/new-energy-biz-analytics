"""Build fail-closed DAY-1 full-functional acceptance evidence.

The builder deliberately separates discovery evidence from functional outcomes:
``status: PASS`` in the first-pass route inventory means that a page was visible;
it never proves that the page or one of its controls worked.  Final coverage is
computed only by joining outcome records to the frozen, stable IDs in the route,
interaction, and user-visible feature inventories.

Canonical functional evidence accepted by this tool may contain these fields::

    {
      "status": "PASS|FAIL|UNKNOWN",
      "feature_inventory": [
        {"id": "FEATURE-...", "page_id": "OVERVIEW", "category": "chart",
         "name": "..."}
      ],
      "page_results": [{"id": "OVERVIEW", "status": "PASS"}],
      "interaction_results": [{"id": "PAGE-...", "status": "PASS"}],
      "feature_results": [{"id": "FEATURE-...", "status": "PASS"}],
      "gates": {"CHATBI": "PASS"},
      "bugs": [],
      "console_errors": [], "page_errors": [], "request_failures": [],
      "blocking_responses": [],
      "frontend_data_label_scan": {
        "status": "PASS", "dom_scan_performed": true, "findings": []
      }
    }

``NOT_APPLICABLE`` is accepted only when the same record has a non-empty
``reason``.  Missing evidence, malformed IDs, duplicate IDs, unexpected result
IDs, FAIL, UNKNOWN, and invalid N/A records can never produce final PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs" / "platformization" / "day1-functional-acceptance" / "evidence"
GENERATOR = "scripts/build_day1_acceptance_evidence.py"
SCHEMA_VERSION = "1.0"

PASS_STATES = {"PASS", "BUG_FIXED_PASS", "AVAILABLE", "CLOSED", "RESOLVED"}
FAIL_STATES = {"FAIL", "FAILED", "ERROR", "BLOCKED", "OPEN", "UNRESOLVED"}
UNKNOWN_STATES = {
    "", "UNKNOWN", "MISSING", "NOT_TESTED", "NOT_RUN", "PENDING", "SKIPPED",
    "INCOMPLETE", "CONDITIONAL",
}
NA_STATES = {"NOT_APPLICABLE", "N/A", "NA"}
TERMINAL_COVERED_STATES = PASS_STATES | FAIL_STATES | NA_STATES

FINAL_FILENAMES = (
    "frontend-functional-inventory.json",
    "route-inventory.json",
    "interaction-inventory.json",
    "first-pass-results.json",
    "missing-data-matrix.json",
    "functional-bug-list.json",
    "data-seed-result.json",
    "kpi-audit.json",
    "chart-audit.json",
    "chatbi-audit.json",
    "model-provider-audit.json",
    "rag-audit.json",
    "memory-audit.json",
    "p6-audit.json",
    "console-network-audit.json",
    "frontend-data-label-scan.json",
    "ui-layout-freeze-report.json",
    "second-pass-results.json",
    "one-click-start.json",
    "second-start.json",
    "final-functional-acceptance.json",
)

HARD_GATES = (
    "ALL_ROUTES_TESTED",
    "ALL_VISIBLE_FUNCTIONS_TESTED",
    "ALL_BUTTONS",
    "ALL_FORMS",
    "ALL_FILTERS",
    "ALL_CHARTS",
    "ALL_KPI_CARDS",
    "ALL_TABLES",
    "ALL_DIALOGS",
    "ALL_EXPORTS",
    "ALL_UPLOADS",
    "CHATBI",
    "SQLBOT",
    "KIMI",
    "MIMO",
    "DEEPSEEK",
    "RAG",
    "MEMORY",
    "DIAGNOSTICS",
    "ALERT",
    "REPORT",
    "METRIC_GOVERNANCE",
    "NO_FRONTEND_MOCK",
    "NO_FRONTEND_DATA_SOURCE_LABEL",
    "DB_API_FRONTEND_CHAIN",
    "TREND_DATA",
    "CONSOLE_ERRORS",
    "BLOCKING_NETWORK_ERRORS",
    "UI_LAYOUT_UNCHANGED",
    "ONE_CLICK_START",
    "SECOND_START",
    "BACKEND_REGRESSION",
    "PLAYWRIGHT",
)

OPTIONAL_NA_GATES = {"ALL_UPLOADS"}

AUDIT_SPECS: dict[str, tuple[str, ...]] = {
    "missing-data-matrix.json": ("missing_data_matrix", "missing-data-matrix"),
    "data-seed-result.json": ("data_seed_result", "data-seed-result"),
    "kpi-audit.json": ("kpi_audit", "kpi-audit"),
    "chart-audit.json": ("chart_audit", "chart-audit"),
    "chatbi-audit.json": ("chatbi_audit", "chatbi-audit"),
    "model-provider-audit.json": ("model_provider_audit", "model-provider-audit"),
    "rag-audit.json": ("rag_audit", "rag-audit"),
    "memory-audit.json": ("memory_audit", "memory-audit"),
    "p6-audit.json": ("p6_audit", "p6-audit"),
}

SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".json"}
STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _status(value: Any) -> str:
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if value is None:
        return "UNKNOWN"
    normalized = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "SUCCESS": "PASS",
        "PASSED": "PASS",
        "OK": "PASS",
        "PASS/AVAILABLE": "AVAILABLE",
        "PASS_OR_AVAILABLE": "AVAILABLE",
        "BOUNDARY_PASS": "PASS",
        "BUGFIXEDPASS": "BUG_FIXED_PASS",
        "NOTAPPLICABLE": "NOT_APPLICABLE",
        "NOT_AVAILABLE": "UNKNOWN",
    }
    return aliases.get(normalized, normalized)


def _reason(record: Mapping[str, Any]) -> str:
    for key in ("reason", "n_a_reason", "na_reason", "justification", "note"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_valid_na(status: str, reason: str) -> bool:
    return status in NA_STATES and bool(reason.strip())


def _is_pass(status: str) -> bool:
    return status in PASS_STATES


def _is_generated(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("generated_by") == GENERATOR


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _resolve(root: Path, value: Path | None) -> Path | None:
    if value is None:
        return None
    return value if value.is_absolute() else root / value


def _read_json(path: Path, role: str, issues: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not path.is_file():
        issues.append({"code": "MISSING_INPUT", "role": role, "path": str(path)})
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        issues.append({"code": "INVALID_JSON", "role": role, "path": str(path), "detail": str(error)})
        return None
    if not isinstance(payload, dict):
        issues.append({"code": "INVALID_INPUT_ROOT", "role": role, "path": str(path)})
        return None
    return payload


def _first_existing(paths: Iterable[Path], *, allow_generated: bool = False) -> Path | None:
    for path in paths:
        if not path.is_file():
            continue
        if allow_generated:
            return path
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return path
        if not _is_generated(payload):
            return path
    return None


def _artifact(path: Path, root: Path, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "path": _relative(path, root),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _base(evidence_type: str, status: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": evidence_type,
        "generated_at": _now(),
        "generated_by": GENERATOR,
        "status": status,
    }


def _stable_records(
    records: Any,
    *,
    entity: str,
    id_keys: Sequence[str],
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(records, list):
        issues.append({"code": "MISSING_STABLE_INVENTORY", "entity": entity})
        return [], []
    normalized: list[dict[str, Any]] = []
    ids: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            issues.append({"code": "INVALID_INVENTORY_RECORD", "entity": entity, "index": index})
            continue
        raw_id = next((item.get(key) for key in id_keys if item.get(key) is not None), None)
        stable_id = str(raw_id or "").strip()
        if not STABLE_ID.fullmatch(stable_id):
            issues.append({"code": "INVALID_STABLE_ID", "entity": entity, "index": index, "id": stable_id})
            continue
        if stable_id in seen:
            issues.append({"code": "DUPLICATE_STABLE_ID", "entity": entity, "id": stable_id})
            continue
        seen.add(stable_id)
        copy = dict(item)
        copy["id"] = stable_id
        normalized.append(copy)
        ids.append(stable_id)
    if not ids:
        issues.append({"code": "EMPTY_STABLE_INVENTORY", "entity": entity})
    return normalized, ids


def _load_route_inventory(payload: dict[str, Any] | None, issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    if payload is None:
        return [], []
    records, ids = _stable_records(
        payload.get("page_states"), entity="page", id_keys=("id", "page_id", "route_id"), issues=issues,
    )
    declared = payload.get("page_state_denominator")
    if not isinstance(declared, int) or declared != len(ids):
        issues.append({
            "code": "ROUTE_DENOMINATOR_MISMATCH",
            "declared": declared,
            "stable_id_count": len(ids),
        })
    return records, ids


def _load_interaction_inventory(payload: dict[str, Any] | None, issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    if payload is None:
        return [], []
    records, ids = _stable_records(
        payload.get("controls"), entity="interaction", id_keys=("id", "control_id", "interaction_id"), issues=issues,
    )
    declared = payload.get("deduplicated_control_count")
    if not isinstance(declared, int) or declared != len(ids):
        issues.append({
            "code": "INTERACTION_DENOMINATOR_MISMATCH",
            "declared": declared,
            "stable_id_count": len(ids),
        })
    return records, ids


def _containers(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = [payload]
    for key in ("results", "inventory", "acceptance", "functional", "first_pass", "second_pass", "audits"):
        value = payload.get(key)
        if isinstance(value, dict):
            result.append(value)
    return result


def _find_lists(payload: Mapping[str, Any], keys: Sequence[str]) -> list[list[Any]]:
    found: list[list[Any]] = []
    for container in _containers(payload):
        for key in keys:
            value = container.get(key)
            if isinstance(value, list):
                found.append(value)
    return found


def _find_section(payload: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for container in _containers(payload):
        for key in keys:
            if key in container:
                return container[key]
    return None


OUTCOME_KEYS = {
    "page": ("page_results", "route_results", "pages", "routes"),
    "interaction": ("interaction_results", "control_results", "interactions", "controls"),
    "feature": ("feature_results", "function_results", "user_visible_function_results", "features"),
}

OUTCOME_ID_KEYS = {
    "page": ("id", "page_id", "route_id"),
    "interaction": ("id", "control_id", "interaction_id"),
    "feature": ("id", "feature_id", "function_id"),
}


def _extract_outcomes(
    payload: Mapping[str, Any], *, entity: str, source: str, phase: str, issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen_in_source: set[str] = set()
    for records in _find_lists(payload, OUTCOME_KEYS[entity]):
        for item in records:
            if not isinstance(item, dict) or "status" not in item:
                continue
            raw_id = next((item.get(key) for key in OUTCOME_ID_KEYS[entity] if item.get(key) is not None), None)
            stable_id = str(raw_id or "").strip()
            if not STABLE_ID.fullmatch(stable_id):
                issues.append({"code": "INVALID_RESULT_ID", "entity": entity, "source": source, "id": stable_id})
                continue
            if stable_id in seen_in_source:
                issues.append({"code": "DUPLICATE_RESULT_ID", "entity": entity, "source": source, "id": stable_id})
                continue
            seen_in_source.add(stable_id)
            status = _status(item.get("status"))
            reason = _reason(item)
            if status in NA_STATES and not reason:
                issues.append({"code": "N_A_WITHOUT_REASON", "entity": entity, "source": source, "id": stable_id})
                status = "UNKNOWN"
            output.append({
                "id": stable_id,
                "status": status,
                "reason": reason,
                "source": source,
                "phase": phase,
            })
    # A flat result stream is also supported when each record declares its kind.
    for records in _find_lists(payload, ("results", "test_results")):
        for item in records:
            if not isinstance(item, dict) or "status" not in item:
                continue
            kind = str(item.get("kind") or item.get("entity") or "").strip().lower()
            if kind not in {entity, f"{entity}_result"}:
                continue
            raw_id = next((item.get(key) for key in OUTCOME_ID_KEYS[entity] if item.get(key) is not None), None)
            stable_id = str(raw_id or "").strip()
            if not STABLE_ID.fullmatch(stable_id) or stable_id in seen_in_source:
                issues.append({"code": "INVALID_OR_DUPLICATE_RESULT_ID", "entity": entity, "source": source, "id": stable_id})
                continue
            seen_in_source.add(stable_id)
            status = _status(item.get("status"))
            reason = _reason(item)
            if status in NA_STATES and not reason:
                issues.append({"code": "N_A_WITHOUT_REASON", "entity": entity, "source": source, "id": stable_id})
                status = "UNKNOWN"
            output.append({"id": stable_id, "status": status, "reason": reason, "source": source, "phase": phase})
    if entity == "feature" and payload.get("evidence_type") == "day1_full_functional_playwright_raw":
        steps = payload.get("steps")
        if isinstance(steps, list):
            for item in steps:
                if not isinstance(item, dict):
                    continue
                stable_id = str(item.get("id") or "").strip()
                if not STABLE_ID.fullmatch(stable_id) or stable_id in seen_in_source:
                    issues.append({"code": "INVALID_OR_DUPLICATE_RESULT_ID", "entity": entity, "source": source, "id": stable_id})
                    continue
                seen_in_source.add(stable_id)
                output.append({
                    "id": stable_id,
                    "status": _status(item.get("status")),
                    "reason": _reason(item),
                    "source": source,
                    "phase": phase,
                })
    return output


def _merge_outcomes(outcomes: Sequence[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    final: dict[str, dict[str, Any]] = {}
    history: dict[str, list[dict[str, Any]]] = {}
    for outcome in outcomes:
        history.setdefault(outcome["id"], []).append(outcome)
        final[outcome["id"]] = outcome
    return final, history


def _coverage(
    stable_ids: Sequence[str],
    final_outcomes: Mapping[str, Mapping[str, Any]],
    *,
    entity: str,
) -> dict[str, Any]:
    known = set(stable_ids)
    unexpected = sorted(set(final_outcomes) - known)
    records: list[dict[str, Any]] = []
    covered = passed = valid_na = failed = 0
    missing: list[str] = []
    unknown: list[str] = []
    for stable_id in stable_ids:
        outcome = final_outcomes.get(stable_id)
        if outcome is None:
            status, reason = "UNKNOWN", "no functional outcome for frozen stable ID"
            missing.append(stable_id)
        else:
            status, reason = _status(outcome.get("status")), str(outcome.get("reason") or "")
        if status in TERMINAL_COVERED_STATES and not (status in NA_STATES and not reason):
            covered += 1
        else:
            unknown.append(stable_id)
        if _is_pass(status):
            passed += 1
        elif _is_valid_na(status, reason):
            valid_na += 1
        elif status in FAIL_STATES:
            failed += 1
        records.append({"id": stable_id, "status": status, "reason": reason})
    denominator = len(stable_ids)
    applicable = denominator - valid_na
    coverage_percent = round(100.0 * covered / denominator, 2) if denominator else 0.0
    pass_rate = round(100.0 * passed / applicable, 2) if applicable else 0.0
    acceptance_status = "PASS" if (
        denominator > 0
        and coverage_percent == 100.0
        and pass_rate == 100.0
        and failed == 0
        and not unknown
        and not unexpected
    ) else "FAIL"
    return {
        "entity": entity,
        "denominator": denominator,
        "covered": covered,
        "coverage_percent": coverage_percent,
        "applicable_denominator": applicable,
        "passed": passed,
        "valid_not_applicable": valid_na,
        "failed": failed,
        "pass_rate_percent": pass_rate,
        "acceptance_status": acceptance_status,
        "missing_ids": missing,
        "unknown_ids": sorted(set(unknown)),
        "unexpected_result_ids": unexpected,
        "results": records,
    }


def _feature_inventory(
    payloads: Sequence[tuple[Path, Mapping[str, Any]]],
    page_ids: set[str],
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    ids: list[str] = []
    seen: set[str] = set()
    for path, payload in payloads:
        lists = _find_lists(payload, ("feature_inventory", "user_visible_feature_inventory", "functional_inventory"))
        if "inventory" in path.name.lower() and isinstance(payload.get("features"), list):
            lists.append(payload["features"])
        inventory_container = _find_section(payload, ("frontend_functional_inventory",))
        if isinstance(inventory_container, dict) and isinstance(inventory_container.get("features"), list):
            lists.append(inventory_container["features"])
        # DAY-1 Playwright's acceptanceStep ID is the executable stable feature
        # ID.  It is an explicit frozen list, unlike an anonymous test count.
        if payload.get("evidence_type") == "day1_full_functional_playwright_raw" and isinstance(payload.get("steps"), list):
            lists.append([
                {
                    "id": item.get("id"),
                    "page_id": _feature_page_id(str(item.get("id") or "")),
                    "category": _feature_category(str(item.get("id") or "")),
                    "name": item.get("title") or item.get("id"),
                }
                for item in payload["steps"]
                if isinstance(item, dict)
            ])
        for source_records in lists:
            for index, item in enumerate(source_records):
                if not isinstance(item, dict):
                    issues.append({"code": "INVALID_FEATURE_INVENTORY_RECORD", "source": str(path), "index": index})
                    continue
                stable_id = str(item.get("id") or item.get("feature_id") or item.get("function_id") or "").strip()
                if not STABLE_ID.fullmatch(stable_id):
                    issues.append({"code": "INVALID_STABLE_ID", "entity": "feature", "source": str(path), "id": stable_id})
                    continue
                if stable_id in seen:
                    # Repeated identical inventories are harmless; conflicting metadata is not.
                    existing = next(record for record in records if record["id"] == stable_id)
                    comparable = {key: item.get(key) for key in ("page_id", "category", "name")}
                    if any(comparable[key] not in (None, existing.get(key)) for key in comparable):
                        issues.append({"code": "CONFLICTING_FEATURE_ID", "id": stable_id, "source": str(path)})
                    continue
                page_id = str(item.get("page_id") or "").strip()
                if page_id and page_id not in page_ids:
                    issues.append({"code": "FEATURE_REFERENCES_UNKNOWN_PAGE", "id": stable_id, "page_id": page_id})
                seen.add(stable_id)
                record = dict(item)
                record["id"] = stable_id
                record["page_id"] = page_id
                record.setdefault("category", "uncategorized")
                record.setdefault("name", stable_id)
                record["inventory_source"] = str(path)
                records.append(record)
                ids.append(stable_id)
    if not ids:
        issues.append({"code": "EMPTY_STABLE_INVENTORY", "entity": "feature"})
    return records, ids


def _feature_category(feature_id: str) -> str:
    prefix = feature_id.split("-", 1)[0].upper()
    return {
        "AUTH": "authentication",
        "GLOBAL": "global-control",
        "CHATBI": "chatbi",
        "MEMORY": "memory",
        "SKILLS": "skills",
        "KNOWLEDGE": "knowledge",
        "MAPPING": "data-integration",
        "GOVERNANCE": "governance",
        "P6": "p6-loop",
        "BOUNDARY": "product-boundary",
    }.get(prefix, "page-functional-flow")


def _feature_page_id(feature_id: str) -> str:
    value = feature_id.upper()
    exact = {
        "DASHBOARD": "DASHBOARD",
        "REVENUE": "REVENUE",
        "MARGIN": "MARGIN",
        "STATIONS": "STATIONS",
        "DEVICES": "DEVICES",
        "CHATBI": "CHATBI",
        "MEMORY": "MEMORY",
        "SKILLS": "SKILLS",
        "KNOWLEDGE": "KNOWLEDGE",
        "MAPPING": "MAPPING",
        "GOVERNANCE": "GOVERNANCE-OVERVIEW",
    }
    prefix = value.split("-", 1)[0]
    if prefix in exact:
        return exact[prefix]
    if value.startswith("P6-ALERT"):
        return "ALERTS"
    if value.startswith("P6-REPORT"):
        return "REPORTS"
    if value.startswith("P6-METRIC"):
        return "METRICS"
    if value.startswith("AUTH-001"):
        return "LOGIN"
    if value.startswith("AUTH-") or value.startswith("GLOBAL-") or value.startswith("BOUNDARY-"):
        return "OVERVIEW"
    return ""


def _planned_feature_inventory(root: Path, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spec = root / "frontend" / "e2e" / "day1-full-functional.spec.ts"
    if not spec.is_file():
        return []
    try:
        text = spec.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        issues.append({"code": "FUNCTIONAL_SPEC_UNREADABLE", "path": str(spec), "detail": str(error)})
        return []
    pattern = re.compile(
        r"\bacceptanceStep\s*\(\s*(['\"])(?P<id>[^'\"]+)\1\s*,\s*(['\"])(?P<title>[^'\"]+)\3",
        re.DOTALL,
    )
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in pattern.finditer(text):
        stable_id = match.group("id").strip()
        if not STABLE_ID.fullmatch(stable_id):
            issues.append({"code": "INVALID_PLANNED_FEATURE_ID", "id": stable_id, "path": str(spec)})
            continue
        if stable_id in seen:
            issues.append({"code": "DUPLICATE_PLANNED_FEATURE_ID", "id": stable_id, "path": str(spec)})
            continue
        seen.add(stable_id)
        records.append({
            "id": stable_id,
            "page_id": _feature_page_id(stable_id),
            "category": _feature_category(stable_id),
            "name": re.sub(r"\s+", " ", match.group("title")).strip(),
            "inventory_source": _relative(spec, root),
            "source_line": _line(text, match.start()),
        })
    return records


def _merge_feature_inventories(
    primary: Sequence[Mapping[str, Any]],
    additional: Sequence[Mapping[str, Any]],
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    result: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for item in list(primary) + list(additional):
        stable_id = str(item.get("id") or "").strip()
        if not STABLE_ID.fullmatch(stable_id):
            continue
        if stable_id in by_id:
            existing = by_id[stable_id]
            for key in ("page_id", "category"):
                if item.get(key) and existing.get(key) and item.get(key) != existing.get(key):
                    issues.append({"code": "CONFLICTING_FEATURE_ID", "id": stable_id, "field": key})
            continue
        record = dict(item)
        record["id"] = stable_id
        by_id[stable_id] = record
        result.append(record)
    return result, [item["id"] for item in result]


RAW_STEP_PAGE_MAP: dict[str, tuple[str, ...]] = {
    "AUTH-001": ("LOGIN", "OIDC-CALLBACK"),
    "AUTH-002": ("OVERVIEW",),
    "AUTH-003": ("OVERVIEW",),
    "GLOBAL-001": ("OVERVIEW",),
    "DASHBOARD-001": ("DASHBOARD",),
    "REVENUE-001": ("REVENUE",),
    "MARGIN-001": ("MARGIN",),
    "STATIONS-001": ("STATIONS",),
    "DEVICES-001": ("DEVICES",),
    "CHATBI-001": ("CHATBI",),
    "CHATBI-002": ("CHATBI",),
    "MEMORY-001": ("MEMORY",),
    "SKILLS-001": ("SKILLS",),
    "KNOWLEDGE-001": ("KNOWLEDGE",),
    "MAPPING-001": ("MAPPING",),
    "MAPPING-002": ("MAPPING",),
    "GOVERNANCE-001": (
        "GOVERNANCE-OVERVIEW", "GOVERNANCE-IDENTITY", "GOVERNANCE-CREDENTIALS",
        "GOVERNANCE-RETENTION", "GOVERNANCE-AUDIT", "GOVERNANCE-RELEASE",
        "GOVERNANCE-PREPRODUCTION", "GOVERNANCE-PRODUCTION",
    ),
    "P6-ALERT-001": ("ALERTS",),
    "P6-REPORT-001": ("REPORTS",),
    "P6-METRIC-001": ("METRICS",),
}


def _raw_playwright_page_outcomes(
    payload: Mapping[str, Any],
    *,
    source: str,
    phase: str,
) -> list[dict[str, Any]]:
    if payload.get("evidence_type") != "day1_full_functional_playwright_raw":
        return []
    by_page: dict[str, list[str]] = {}
    steps = payload.get("steps")
    if isinstance(steps, list):
        for item in steps:
            if not isinstance(item, dict):
                continue
            step_id = str(item.get("id") or "").strip()
            for page_id in RAW_STEP_PAGE_MAP.get(step_id, ()):
                by_page.setdefault(page_id, []).append(_status(item.get("status")))
    results: list[dict[str, Any]] = []
    for page_id, statuses in by_page.items():
        if any(status in FAIL_STATES for status in statuses):
            status = "FAIL"
        elif any(status in UNKNOWN_STATES for status in statuses):
            status = "UNKNOWN"
        elif any(_is_pass(status) for status in statuses):
            status = "PASS"
        else:
            status = "UNKNOWN"
        results.append({
            "id": page_id,
            "status": status,
            "reason": "mapped from executable acceptanceStep stable ID",
            "source": source,
            "phase": phase,
        })
    return results


def _functional_page_metadata(
    payloads: Sequence[tuple[Path, Mapping[str, Any]]],
    known_page_ids: set[str],
    issues: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for path, payload in payloads:
        lists = _find_lists(payload, ("page_inventory", "frontend_page_inventory"))
        section = _find_section(payload, ("frontend_functional_inventory",))
        if isinstance(section, dict) and isinstance(section.get("pages"), list):
            lists.append(section["pages"])
        if "inventory" in path.name.lower() and isinstance(payload.get("pages"), list):
            lists.append(payload["pages"])
        for records in lists:
            for item in records:
                if not isinstance(item, dict):
                    continue
                page_id = str(item.get("id") or item.get("page_id") or item.get("route_id") or "").strip()
                if page_id not in known_page_ids:
                    issues.append({"code": "PAGE_METADATA_UNKNOWN_ID", "id": page_id, "source": str(path)})
                    continue
                current = metadata.setdefault(page_id, {})
                for key in ("route", "page_name", "name", "visible", "auth_required", "roles", "parent", "api_endpoints"):
                    if key not in item:
                        continue
                    if key in current and current[key] != item[key]:
                        issues.append({"code": "CONFLICTING_PAGE_METADATA", "id": page_id, "field": key, "source": str(path)})
                    current[key] = item[key]
                current["inventory_source"] = str(path)
    return metadata


def _source_files(frontend_dir: Path) -> list[Path]:
    if not frontend_dir.is_dir():
        return []
    return sorted(path for path in frontend_dir.rglob("*") if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _finding_id(rule: str, relative_path: str, line: int, excerpt: str) -> str:
    digest = hashlib.sha256(f"{rule}:{relative_path}:{line}:{excerpt}".encode("utf-8")).hexdigest()[:12].upper()
    return f"STATIC-{rule.upper().replace('_', '-')}-{digest}"


def _static_frontend_scan(frontend_dir: Path, root: Path) -> dict[str, Any]:
    files = _source_files(frontend_dir)
    mock_findings: list[dict[str, Any]] = []
    interaction_risks: list[dict[str, Any]] = []
    declaration_counts = {tag: 0 for tag in ("button", "input", "select", "textarea", "a", "summary")}
    business_tokens = re.compile(
        r"revenue|margin|profit|station|device|metric|trend|kpi|order|alert|report|充电|收入|毛利|场站|设备|指标|趋势|订单",
        re.IGNORECASE,
    )
    for path in files:
        relative_path = _relative(path, root)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        seen: set[tuple[str, int]] = set()

        def add_mock(rule: str, match: re.Match[str], detail: str) -> None:
            line = _line(text, match.start())
            key = (rule, line)
            if key in seen:
                return
            seen.add(key)
            excerpt = text[match.start():match.end()].replace("\n", " ")[:220]
            mock_findings.append({
                "id": _finding_id(rule, relative_path, line, excerpt),
                "rule": rule,
                "path": relative_path,
                "line": line,
                "detail": detail,
                "excerpt": excerpt,
            })

        for match in re.finditer(r"\bMath\s*\.\s*random\s*\(", text):
            add_mock("math_random", match, "Math.random is prohibited in frontend business-data paths")
        for match in re.finditer(r"(?im)^.*(?:mock|fixture|fake)[^\n]*$", text):
            if business_tokens.search(match.group(0)) or re.search(r"(?:from|import|require)\s*\(?[\"'][^\"']*(?:mock|fixture)", match.group(0), re.I):
                add_mock("mock_fixture_business_data", match, "mock/fixture/fake business-data reference")
        if path.suffix.lower() == ".json" and business_tokens.search(text):
            match = re.search(r"\S", text)
            if match:
                add_mock("static_business_json", match, "business-shaped static JSON under frontend/src")
        setter_pattern = re.compile(
            r"set(?:Summary|Trend|Stations?|Devices?|Revenue|Margin|Profit|Metrics?|Rows|Chart|Kpi|BusinessData)\s*"
            r"\(\s*(?:\[(?!\s*\])|\{\s*[A-Za-z_$\"'])",
            re.IGNORECASE,
        )
        catch_patterns = (
            re.compile(r"\bcatch\s*\([^)]*\)\s*\{(?P<body>.{0,3500}?)\}", re.DOTALL),
            re.compile(r"\.\s*catch\s*\(\s*[^=()]*=>\s*\{(?P<body>.{0,3500}?)\}\s*\)", re.DOTALL),
        )
        for catch_pattern in catch_patterns:
            for match in catch_pattern.finditer(text):
                setter = setter_pattern.search(match.group("body"))
                if setter:
                    absolute_start = match.start("body") + setter.start()
                    synthetic = re.match(r".{1,240}", text[absolute_start:], re.DOTALL)
                    if synthetic:
                        add_mock("api_failure_fake_fallback", _OffsetMatch(synthetic, absolute_start), "API catch path injects non-empty business-shaped state")
        expression_fallback = re.compile(
            r"\.\s*catch\s*\(\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)?\s*=>\s*"
            r"(?P<body>\[[^\]]+\]|\(\s*\{.{1,1500}?\}\s*\))\s*\)",
            re.DOTALL,
        )
        for match in expression_fallback.finditer(text):
            if business_tokens.search(match.group("body")) or re.search(r"[\"']?(?:value|metrics?|points?|rows)[\"']?\s*:", match.group("body"), re.I):
                add_mock("api_failure_fake_fallback", match, "Promise rejection path returns non-empty business-shaped data")
        tag_pattern = re.compile(r"<(button|input|select|textarea|a|summary)\b(?P<attrs>[^>]*)>", re.IGNORECASE | re.DOTALL)
        for match in tag_pattern.finditer(text):
            tag = match.group(1).lower()
            declaration_counts[tag] += 1
            attrs = match.group("attrs")
            if tag in {"button", "a", "summary"}:
                actionable = (
                    "onClick" in attrs
                    or re.search(r"\btype\s*=\s*[\"']submit[\"']", attrs, re.I)
                    or (tag == "a" and re.search(r"\bhref\s*=", attrs, re.I))
                    or tag == "summary"
                )
                disabled = re.search(r"\bdisabled(?:\s|=|$)", attrs) is not None
                if not actionable and not disabled and tag != "summary":
                    line = _line(text, match.start())
                    excerpt = match.group(0).replace("\n", " ")[:220]
                    interaction_risks.append({
                        "id": _finding_id("missing_handler", relative_path, line, excerpt),
                        "rule": "missing_handler",
                        "path": relative_path,
                        "line": line,
                        "tag": tag,
                        "excerpt": excerpt,
                    })
    return {
        "files_scanned": len(files),
        "declaration_counts": declaration_counts,
        "mock_scan": {
            "status": "PASS" if files and not mock_findings else "FAIL" if mock_findings else "UNKNOWN",
            "rules": ["Math.random", "mock/fixture business data", "static business JSON", "API-failure fake fallback"],
            "finding_count": len(mock_findings),
            "findings": mock_findings,
        },
        "interaction_static_risks": interaction_risks,
    }


class _OffsetMatch:
    """Small adapter used to retain absolute offsets for a nested regex match."""

    def __init__(self, match: re.Match[str], offset: int) -> None:
        self._match = match
        self._offset = offset

    def start(self) -> int:
        return self._offset + self._match.start()

    def end(self) -> int:
        return self._offset + self._match.end()

    def group(self, *args: Any) -> Any:
        return self._match.group(*args)


def _mask_component(text: str, component: str) -> str:
    start = re.search(rf"(?m)^(?:export\s+)?function\s+{re.escape(component)}\b", text)
    if not start:
        return text
    next_function = re.search(r"(?m)^(?:export\s+)?function\s+[A-Za-z_$][\w$]*\b", text[start.end():])
    end = start.end() + next_function.start() if next_function else len(text)
    return text[:start.start()] + ("\n" * text[start.start():end].count("\n")) + text[end:]


def _global_status_contract(files: Sequence[Path], root: Path) -> dict[str, Any]:
    overview = next((path for path in files if path.name == "overview.tsx"), None)
    if overview is None:
        return {"status": "UNKNOWN", "path": None, "requirements": {}, "missing": ["component"]}
    text = overview.read_text(encoding="utf-8-sig")
    start = re.search(r"(?m)^function\s+GlobalDataStatus\b", text)
    end = re.search(r"(?m)^function\s+MiniLine\b", text)
    body = text[start.start():end.start()] if start and end and end.start() > start.start() else ""
    requirements = {
        "nature": bool(re.search(r"模拟数据|真实数据|开源数据|数据性质|classification|data_classification", body, re.I)),
        "time_range": bool(re.search(r"统计期间|时间范围|data_time_range", body, re.I)),
        "source": bool(re.search(r"数据来源|metadata\s*\.\s*source|来源[：:]", body, re.I)),
        "run_id": bool(re.search(r"run_id|analysis_run_id", body, re.I)),
    }
    missing = [name for name, passed in requirements.items() if not passed]
    return {
        "status": "PASS" if body and not missing else "FAIL" if body else "UNKNOWN",
        "path": _relative(overview, root),
        "requirements": requirements,
        "missing": missing,
        "selector": ".global-data-status",
    }


def _static_label_scan(frontend_dir: Path, root: Path) -> dict[str, Any]:
    files = _source_files(frontend_dir)
    excluded_files = {"governance.tsx", "preproduction.tsx", "production-acceptance.tsx"}
    excluded_components = {
        "overview.tsx": ("GlobalDataStatus", "MappingPage", "BoundaryPage"),
        "business-loop.tsx": ("ReportGovernancePage", "MetricGovernancePage"),
    }
    forbidden = re.compile(r"模拟数据|真实生产数据|开源真实数据|开放数据|数据性质|数据来源|数据源性质|来源[：:]", re.I)
    findings: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for path in files:
        if path.suffix.lower() not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        relative_path = _relative(path, root)
        text = path.read_text(encoding="utf-8-sig")
        if path.name in excluded_files:
            exclusions.append({"path": relative_path, "reason": "governance/truth page"})
            continue
        for component in excluded_components.get(path.name, ()):
            masked = _mask_component(text, component)
            if masked != text:
                exclusions.append({"path": relative_path, "component": component, "reason": "governance/truth component"})
                text = masked
        # The adjudication explicitly exempts the one global status region.
        # Dedicated governance/truth pages are excluded above; ordinary page
        # elements merely named "*-truth" are not automatically exempt.
        kept_lines: list[str] = []
        for source_line in text.splitlines(keepends=True):
            if re.search(r"className\s*=\s*[\"'][^\"']*global-data-status[^\"']*[\"']", source_line, re.I):
                kept_lines.append("\n" if source_line.endswith("\n") else "")
            else:
                kept_lines.append(source_line)
        text = "".join(kept_lines)
        for match in forbidden.finditer(text):
            line = _line(text, match.start())
            excerpt_start = text.rfind("\n", 0, match.start()) + 1
            excerpt_end = text.find("\n", match.end())
            if excerpt_end < 0:
                excerpt_end = len(text)
            excerpt = text[excerpt_start:excerpt_end].strip()[:240]
            findings.append({
                "id": _finding_id("business_data_label", relative_path, line, excerpt),
                "path": relative_path,
                "line": line,
                "term": match.group(0),
                "excerpt": excerpt,
            })
    contract = _global_status_contract(files, root)
    status = "UNKNOWN" if not files else "PASS"
    if findings or contract["status"] == "FAIL":
        status = "FAIL"
    elif contract["status"] != "PASS":
        status = "UNKNOWN"
    return {
        "status": status,
        "files_scanned": len(files),
        "ordinary_business_component_finding_count": len(findings),
        "ordinary_business_component_findings": findings,
        "excluded_scopes": exclusions,
        "adjudication": "exclude .global-data-status and governance/truth pages; require global nature, time, source, run_id",
        "global_data_status_contract": contract,
    }


def _extract_dom_label_audit(payloads: Sequence[tuple[Path, Mapping[str, Any]]], root: Path) -> dict[str, Any]:
    found = False
    findings: list[dict[str, Any]] = []
    sources: list[str] = []
    explicit_statuses: list[str] = []
    for path, payload in payloads:
        section = _find_section(payload, ("frontend_data_label_scan", "data_label_scan", "dom_data_label_scan"))
        normalized_name = path.name.lower().replace(".raw.json", ".json").replace(".source.json", ".json")
        if section is None and normalized_name == "frontend-data-label-scan.json":
            section = payload
        if not isinstance(section, dict):
            continue
        performed = section.get("dom_scan_performed") is True or section.get("runtime_dom_checked") is True
        if not performed:
            continue
        found = True
        sources.append(_relative(path, root))
        explicit_statuses.append(_status(section.get("status")))
        candidates = section.get("findings") or section.get("dom_findings") or []
        if isinstance(candidates, list):
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                selector = str(item.get("selector") or "")
                page_id = str(item.get("page_id") or "")
                excluded = (
                    item.get("excluded") is True
                    or selector.startswith(".global-data-status")
                    or page_id.startswith("GOVERNANCE-")
                    or str(item.get("scope") or "").lower() in {"governance", "truth"}
                )
                if not excluded:
                    findings.append(dict(item))
    if not found:
        status = "UNKNOWN"
    elif findings or any(value in FAIL_STATES | UNKNOWN_STATES for value in explicit_statuses):
        status = "FAIL"
    else:
        status = "PASS"
    return {
        "status": status,
        "dom_scan_performed": found,
        "sources": sources,
        "finding_count": len(findings),
        "findings": findings,
    }


def _runtime_global_status_contract(payloads: Sequence[tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path, payload in payloads:
        section = _find_section(payload, ("frontend_data_label_scan", "data_label_scan", "dom_data_label_scan"))
        normalized_name = path.name.lower().replace(".raw.json", ".json").replace(".source.json", ".json")
        if section is None and normalized_name == "frontend-data-label-scan.json":
            section = payload
        if not isinstance(section, dict):
            continue
        contract = section.get("global_data_status_contract") or section.get("global_status_contract")
        if not isinstance(contract, dict):
            continue
        requirements_raw = contract.get("requirements") if isinstance(contract.get("requirements"), dict) else contract
        requirements = {
            name: requirements_raw.get(name) is True
            for name in ("nature", "time_range", "source", "run_id")
        }
        records.append({"source": str(path), "requirements": requirements})
    if not records:
        return {"status": "UNKNOWN", "requirements": {}, "sources": []}
    combined = {
        name: all(record["requirements"][name] for record in records)
        for name in ("nature", "time_range", "source", "run_id")
    }
    return {
        "status": "PASS" if all(combined.values()) else "FAIL",
        "requirements": combined,
        "sources": [record["source"] for record in records],
        "observations": records,
    }


def _acceptance_status(payload: Any) -> tuple[str, str]:
    if isinstance(payload, bool):
        return _status(payload), "boolean evidence"
    if isinstance(payload, str):
        status = _status(payload)
        if status in NA_STATES:
            return "UNKNOWN", "scalar NOT_APPLICABLE has no reason"
        return status, "string evidence"
    if not isinstance(payload, dict):
        return "UNKNOWN", "missing or non-object evidence"
    if "missing" in payload and isinstance(payload.get("missing"), bool):
        missing_status = "FAIL" if payload["missing"] else "PASS"
        if payload.get("functional_pass_asserted") is False:
            missing_status = "PASS" if not payload["missing"] else "FAIL"
        return missing_status, f"readiness missing={payload['missing']}"
    adjudication = str(payload.get("adjudication") or "").upper()
    if adjudication:
        if adjudication.endswith("READY_FOR_FUNCTIONAL_TESTING"):
            return "PASS", adjudication
        if "MISSING" in adjudication or "FAIL" in adjudication or "BLOCK" in adjudication:
            return "FAIL", adjudication
    raw = next((payload.get(key) for key in ("status", "final_status", "acceptance_status", "result") if key in payload), None)
    status = _status(raw)
    checks = payload.get("checks")
    if isinstance(checks, dict) and checks:
        values: list[str] = []
        for value in checks.values():
            if isinstance(value, dict):
                nested_status = _status(value.get("status"))
                if nested_status in NA_STATES and not _reason(value):
                    nested_status = "UNKNOWN"
            else:
                nested_status = _status(value)
                if nested_status in NA_STATES:
                    nested_status = "UNKNOWN"
            values.append(nested_status)
        if any(value in FAIL_STATES | UNKNOWN_STATES for value in values):
            return "FAIL", "one or more checks are not PASS"
        if raw is None and all(_is_pass(value) for value in values):
            status = "PASS"
    reason = _reason(payload) or "explicit evidence status"
    if status in NA_STATES and not _reason(payload):
        return "UNKNOWN", "NOT_APPLICABLE has no reason"
    if status not in PASS_STATES | FAIL_STATES | UNKNOWN_STATES | NA_STATES:
        return "UNKNOWN", f"unrecognized status {status}"
    return status, reason


def _generic_audit(
    filename: str,
    section_keys: Sequence[str],
    payloads: Sequence[tuple[Path, Mapping[str, Any]]],
    root: Path,
) -> dict[str, Any]:
    selected: tuple[Path, Any] | None = None
    for path, payload in reversed(payloads):
        section = _find_section(payload, section_keys)
        normalized_name = path.name.lower().replace(".raw.json", ".json").replace(".source.json", ".json")
        if section is None and normalized_name == filename.lower():
            section = payload
        if section is not None:
            selected = (path, section)
            break
    if selected is None:
        return _base(filename.removesuffix(".json").replace("-", "_"), "UNKNOWN") | {
            "reason": "no explicit audit section was supplied",
            "source_artifacts": [],
        }
    path, section = selected
    status, reason = _acceptance_status(section)
    summary: Any = section
    if isinstance(section, dict):
        # Preserve the submitted audit section; it is evidence, not a synthesized PASS.
        summary = section
    return _base(filename.removesuffix(".json").replace("-", "_"), status) | {
        "reason": reason,
        "source_artifacts": [_artifact(path, root, filename.removesuffix(".json"))],
        "submitted_audit": summary,
    }


def _extract_gates(payloads: Sequence[tuple[Path, Mapping[str, Any], str]], root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    final: dict[str, dict[str, Any]] = {}
    history: dict[str, list[dict[str, Any]]] = {}
    for path, payload, phase in payloads:
        mappings: list[Mapping[str, Any]] = []
        for container in _containers(payload):
            for key in ("gates", "hard_gates", "acceptance_gates"):
                value = container.get(key)
                if isinstance(value, dict):
                    mappings.append(value)
        direct = {gate: payload[gate] for gate in HARD_GATES if gate in payload}
        if direct:
            mappings.append(direct)
        for mapping in mappings:
            for raw_name, raw_value in mapping.items():
                name = str(raw_name).strip().upper().replace("-", "_").replace(" ", "_")
                if isinstance(raw_value, dict):
                    status = _status(raw_value.get("status"))
                    reason = _reason(raw_value)
                elif name in {"CONSOLE_ERRORS", "BLOCKING_NETWORK_ERRORS"} and isinstance(raw_value, (int, float)):
                    status = "PASS" if raw_value == 0 else "FAIL"
                    reason = f"observed count={raw_value}"
                else:
                    status = _status(raw_value)
                    reason = "" if status in NA_STATES else "explicit functional evidence gate"
                if status in NA_STATES and not reason:
                    status = "UNKNOWN"
                    reason = "NOT_APPLICABLE has no reason"
                record = {
                    "status": status,
                    "reason": reason,
                    "source": _relative(path, root),
                    "phase": phase,
                }
                history.setdefault(name, []).append(record)
                final[name] = record
    return final, history


def _console_audit(
    first: tuple[Path, Mapping[str, Any]] | None,
    functional: Sequence[tuple[Path, Mapping[str, Any]]],
    root: Path,
) -> dict[str, Any]:
    fields = ("console_errors", "page_errors", "request_failures", "blocking_responses")
    combined = {field: [] for field in fields}
    requests: list[Any] = []
    source_artifacts: list[dict[str, Any]] = []
    functional_observed = False
    sources: list[tuple[Path, Mapping[str, Any], bool]] = []
    if first is not None:
        sources.append((first[0], first[1], False))
    sources.extend((path, payload, True) for path, payload in functional)
    for path, payload, is_functional in sources:
        section = _find_section(payload, ("console_network_audit", "console_network", "network_audit"))
        data = section if isinstance(section, dict) else payload
        observed_here = any(isinstance(data.get(field), list) for field in fields)
        if is_functional and observed_here:
            functional_observed = True
        if observed_here:
            source_artifacts.append(_artifact(path, root, "console_network"))
        for field in fields:
            value = data.get(field)
            if isinstance(value, list):
                combined[field].extend(value)
        if isinstance(data.get("requests"), list):
            requests.extend(data["requests"])
    blocking_from_requests = [
        request for request in requests
        if isinstance(request, dict) and isinstance(request.get("status"), int) and request["status"] >= 400
    ]
    blocking = combined["blocking_responses"] + blocking_from_requests
    error_count = sum(len(combined[field]) for field in ("console_errors", "page_errors", "request_failures"))
    if error_count or blocking:
        status = "FAIL"
    elif first is None or not functional_observed:
        status = "UNKNOWN"
    else:
        status = "PASS"
    return _base("day1_console_network_audit", status) | {
        **combined,
        "blocking_responses": blocking,
        "requests": requests,
        "console_error_count": len(combined["console_errors"]) + len(combined["page_errors"]),
        "request_failure_count": len(combined["request_failures"]),
        "blocking_network_error_count": len(blocking),
        "functional_run_observed": functional_observed,
        "source_artifacts": source_artifacts,
    }


def _extract_layout_results(payloads: Sequence[tuple[Path, Mapping[str, Any]]]) -> tuple[dict[str, dict[str, Any]], dict[str, Mapping[str, Any]]]:
    decisions: dict[str, dict[str, Any]] = {}
    layouts: dict[str, Mapping[str, Any]] = {}
    for path, payload in payloads:
        result_lists = _find_lists(payload, ("layout_results", "ui_layout_results"))
        normalized_name = path.name.lower().replace(".raw.json", ".json").replace(".source.json", ".json")
        section = _find_section(payload, ("ui_layout_freeze_report", "layout_audit"))
        if isinstance(section, dict):
            for key in ("layout_results", "ui_layout_results", "page_results"):
                if isinstance(section.get(key), list):
                    result_lists.append(section[key])
        if normalized_name == "ui-layout-freeze-report.json" and isinstance(payload.get("page_results"), list):
            result_lists.append(payload["page_results"])
        for records in result_lists:
            for item in records:
                if not isinstance(item, dict):
                    continue
                page_id = str(item.get("id") or item.get("page_id") or "")
                if not page_id:
                    continue
                status = _status(item.get("status"))
                reason = _reason(item)
                if status in NA_STATES and not reason:
                    status = "UNKNOWN"
                decisions[page_id] = {"status": status, "reason": reason}
        for records in _find_lists(payload, ("page_results", "pages")):
            for item in records:
                if not isinstance(item, dict):
                    continue
                page_id = str(item.get("id") or item.get("page_id") or "")
                if page_id and isinstance(item.get("layout"), dict):
                    layouts[page_id] = item["layout"]
    return decisions, layouts


def _layout_report(
    pages: Sequence[Mapping[str, Any]],
    second_payloads: Sequence[tuple[Path, Mapping[str, Any]]],
    tolerance_px: float,
) -> dict[str, Any]:
    decisions, final_layouts = _extract_layout_results(second_payloads)
    results: list[dict[str, Any]] = []
    for page in pages:
        page_id = str(page.get("id"))
        if page_id in decisions:
            results.append({"page_id": page_id, **decisions[page_id], "method": "explicit stable-ID layout result"})
            continue
        baseline = page.get("layout")
        final = final_layouts.get(page_id)
        if not isinstance(baseline, dict) or not baseline or not isinstance(final, dict) or not final:
            results.append({"page_id": page_id, "status": "UNKNOWN", "reason": "baseline/final geometry or explicit result missing"})
            continue
        deltas: list[dict[str, Any]] = []
        passed = True
        for selector, base_box in baseline.items():
            final_box = final.get(selector)
            if not isinstance(base_box, dict) or not isinstance(final_box, dict):
                passed = False
                deltas.append({"selector": selector, "status": "MISSING"})
                continue
            component_delta: dict[str, float] = {}
            for dimension in ("x", "y", "width", "height"):
                try:
                    delta = abs(float(final_box[dimension]) - float(base_box[dimension]))
                    limit = max(tolerance_px, abs(float(base_box[dimension])) * 0.02)
                except (KeyError, TypeError, ValueError):
                    passed = False
                    component_delta[dimension] = float("inf")
                    continue
                component_delta[dimension] = round(delta, 3)
                if delta > limit:
                    passed = False
            deltas.append({"selector": selector, "deltas": component_delta})
        results.append({
            "page_id": page_id,
            "status": "PASS" if passed else "FAIL",
            "reason": "geometry within tolerance" if passed else "geometry changed or selector missing",
            "deltas": deltas,
            "method": "baseline/final geometry comparison",
        })
    statuses = [item["status"] for item in results]
    status = "PASS" if results and all(_is_pass(value) or _is_valid_na(value, str(item.get("reason") or "")) for value, item in zip(statuses, results)) else (
        "FAIL" if any(value in FAIL_STATES for value in statuses) else "UNKNOWN"
    )
    return _base("day1_ui_layout_freeze", status) | {
        "tolerance_px": tolerance_px,
        "relative_dimension_tolerance": 0.02,
        "page_denominator": len(pages),
        "page_results": results,
    }


def _attempt_from_runtime(payload: Mapping[str, Any], index: int) -> Any:
    for key in ("attempts", "runs", "starts", "startup_attempts"):
        value = payload.get(key)
        if isinstance(value, list) and len(value) > index:
            return value[index]
    keys = ("one_click_start", "first_start", "cold_start") if index == 0 else ("second_start", "warm_start", "idempotent_restart")
    for key in keys:
        if key in payload:
            return payload[key]
    return payload if index == 0 else None


def _startup_output(name: str, selected: tuple[Path, Any] | None, root: Path) -> dict[str, Any]:
    if selected is None:
        return _base(f"day1_{name}", "UNKNOWN") | {"reason": "startup evidence missing", "source_artifacts": []}
    path, payload = selected
    status, reason = _acceptance_status(payload)
    return _base(f"day1_{name}", status) | {
        "reason": reason,
        "source_artifacts": [_artifact(path, root, name)],
        "submitted_evidence": payload,
    }


def _bugs(
    payloads: Sequence[tuple[Path, Mapping[str, Any]]],
    controls: Sequence[Mapping[str, Any]],
    interaction_coverage: Mapping[str, Any],
    static_scan: Mapping[str, Any],
    label_scan: Mapping[str, Any],
    root: Path,
) -> dict[str, Any]:
    bugs: dict[str, dict[str, Any]] = {}
    explicit_audit = False
    for path, payload in payloads:
        lists = _find_lists(payload, ("bugs", "functional_bugs", "bug_list"))
        if lists:
            explicit_audit = True
        for records in lists:
            for item in records:
                if not isinstance(item, dict):
                    continue
                bug_id = str(item.get("id") or item.get("bug_id") or "").strip()
                if not bug_id:
                    digest = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12].upper()
                    bug_id = f"FUNCTIONAL-BUG-{digest}"
                record = dict(item)
                record["id"] = bug_id
                record["status"] = _status(item.get("status"))
                record["source"] = _relative(path, root)
                bugs[bug_id] = record
    outcomes = {item["id"]: item for item in interaction_coverage.get("results", [])}
    for control in controls:
        if control.get("disabled") is not True:
            continue
        control_id = str(control["id"])
        outcome = outcomes.get(control_id, {})
        outcome_status = _status(outcome.get("status"))
        outcome_reason = str(outcome.get("reason") or "")
        resolved = _is_pass(outcome_status) or _is_valid_na(outcome_status, outcome_reason)
        digest = hashlib.sha256(control_id.encode("utf-8")).hexdigest()[:12].upper()
        bugs[f"VISIBLE-DISABLED-{digest}"] = {
            "id": f"VISIBLE-DISABLED-{digest}",
            "priority": "P1",
            "kind": "visible_disabled_control_requires_classification",
            "control_id": control_id,
            "page_id": control.get("page_id"),
            "name": control.get("name"),
            "status": "RESOLVED" if resolved else "UNKNOWN",
            "resolution": outcome if resolved else None,
        }
    for finding in static_scan.get("mock_scan", {}).get("findings", []):
        bugs[finding["id"]] = {**finding, "priority": "P0", "kind": "frontend_mock_violation", "status": "OPEN"}
    for finding in static_scan.get("interaction_static_risks", []):
        bugs[finding["id"]] = {**finding, "priority": "P1", "kind": "visible_control_missing_handler", "status": "OPEN"}
    for finding in label_scan.get("ordinary_business_component_findings", []):
        bugs[finding["id"]] = {**finding, "priority": "P1", "kind": "ordinary_business_data_label", "status": "OPEN"}
    for missing in label_scan.get("global_data_status_contract", {}).get("missing", []):
        bug_id = f"GLOBAL-DATA-STATUS-{str(missing).upper()}"
        bugs[bug_id] = {
            "id": bug_id,
            "priority": "P1",
            "kind": "global_data_status_contract",
            "missing_requirement": missing,
            "status": "OPEN",
        }
    unresolved = [
        bug for bug in bugs.values()
        if _status(bug.get("status")) not in PASS_STATES
    ]
    status = "FAIL" if unresolved else "PASS" if explicit_audit else "UNKNOWN"
    return _base("day1_functional_bug_list", status) | {
        "explicit_bug_audit_present": explicit_audit,
        "total": len(bugs),
        "unresolved": len(unresolved),
        "by_priority": {
            priority: sum(1 for bug in bugs.values() if str(bug.get("priority") or "").upper() == priority)
            for priority in ("P0", "P1", "P2")
        },
        "bugs": sorted(bugs.values(), key=lambda item: str(item.get("id"))),
    }


def _phase_result(
    phase: str,
    page_ids: Sequence[str],
    control_ids: Sequence[str],
    feature_ids: Sequence[str],
    outcomes: Mapping[str, Sequence[dict[str, Any]]],
    source_count: int,
) -> dict[str, Any]:
    page_final, _ = _merge_outcomes(outcomes["page"])
    interaction_final, _ = _merge_outcomes(outcomes["interaction"])
    feature_final, _ = _merge_outcomes(outcomes["feature"])
    page_metric = _coverage(page_ids, page_final, entity="page")
    interaction_metric = _coverage(control_ids, interaction_final, entity="interaction")
    feature_metric = _coverage(feature_ids, feature_final, entity="feature")
    status = "PASS" if source_count and all(
        metric["acceptance_status"] == "PASS" for metric in (page_metric, interaction_metric, feature_metric)
    ) else "FAIL" if source_count else "UNKNOWN"
    return _base(f"day1_{phase}_results", status) | {
        "functional_evidence_source_count": source_count,
        "page_metrics": page_metric,
        "interaction_metrics": interaction_metric,
        "user_visible_feature_metrics": feature_metric,
    }


def _gate_record(status: str, reason: str, source: str) -> dict[str, Any]:
    return {"status": status, "reason": reason, "source": source}


def _combine_gate(explicit: Mapping[str, Any], derived: Mapping[str, Any]) -> dict[str, Any]:
    """Combine independent claims without allowing one PASS to hide uncertainty."""
    statuses = (_status(explicit.get("status")), _status(derived.get("status")))
    if any(status in FAIL_STATES for status in statuses):
        status = "FAIL"
    elif any(status in UNKNOWN_STATES for status in statuses):
        status = "UNKNOWN"
    elif any(status in NA_STATES for status in statuses):
        status = "NOT_APPLICABLE" if all(status in NA_STATES for status in statuses) else "UNKNOWN"
    elif all(_is_pass(status) for status in statuses):
        status = "PASS"
    else:
        status = "UNKNOWN"
    return {
        "status": status,
        "reason": " | ".join(filter(None, (str(explicit.get("reason") or ""), str(derived.get("reason") or "")))),
        "source": " + ".join(filter(None, (str(explicit.get("source") or ""), str(derived.get("source") or "")))),
        "claims": [dict(explicit), dict(derived)],
    }


def _build(args: argparse.Namespace) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    root = args.repository_root.resolve()
    evidence_dir = args.evidence_dir.resolve()
    output_dir = args.output_dir.resolve()
    frontend_dir = args.frontend_dir.resolve()
    issues: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []

    route_path = args.route_first_pass or evidence_dir / "route-inventory.first-pass.json"
    interaction_path = args.interaction_first_pass or evidence_dir / "interaction-inventory.first-pass.json"
    console_path = args.console_first_pass or evidence_dir / "console-network-audit.first-pass.json"
    route_payload = _read_json(route_path, "route_first_pass", issues)
    interaction_payload = _read_json(interaction_path, "interaction_first_pass", issues)
    console_payload = _read_json(console_path, "console_first_pass", issues)
    if route_payload is not None:
        inputs.append(_artifact(route_path, root, "route_first_pass"))
    if interaction_payload is not None:
        inputs.append(_artifact(interaction_path, root, "interaction_first_pass"))
    if console_payload is not None:
        inputs.append(_artifact(console_path, root, "console_first_pass"))

    page_records, page_ids = _load_route_inventory(route_payload, issues)
    control_records, control_ids = _load_interaction_inventory(interaction_payload, issues)

    functional_paths = list(args.functional_evidence)
    if not functional_paths:
        candidates = (
            "functional-playwright.first-pass.json",
            "day1-functional-playwright.json",
            "first-pass-functional.raw.json",
            "functional-results.raw.json",
            "day1-functional-e2e.json",
        )
        discovered = _first_existing(evidence_dir / name for name in candidates)
        if discovered:
            functional_paths.append(discovered)
    second_paths = list(args.second_pass_evidence)
    if not second_paths:
        candidates = (
            "functional-playwright.second-pass.json",
            "day1-functional-playwright.second-pass.json",
            "second-pass-results.raw.json",
            "second-pass-functional.raw.json",
        )
        discovered = _first_existing(evidence_dir / name for name in candidates)
        if discovered:
            second_paths.append(discovered)

    functional_docs: list[tuple[Path, Mapping[str, Any]]] = []
    second_docs: list[tuple[Path, Mapping[str, Any]]] = []
    for phase, paths, destination in (
        ("first_pass", functional_paths, functional_docs),
        ("second_pass", second_paths, second_docs),
    ):
        for index, path in enumerate(paths):
            payload = _read_json(path, f"{phase}_{index + 1}", issues)
            if payload is not None:
                destination.append((path, payload))
                inputs.append(_artifact(path, root, phase))
    if not functional_docs:
        issues.append({"code": "MISSING_INPUT", "role": "functional_playwright_first_pass"})
    if not second_docs:
        issues.append({"code": "MISSING_INPUT", "role": "functional_playwright_second_pass"})

    feature_sources: list[tuple[Path, Mapping[str, Any]]] = []
    if args.functional_inventory:
        payload = _read_json(args.functional_inventory, "functional_inventory", issues)
        if payload is not None:
            feature_sources.append((args.functional_inventory, payload))
            inputs.append(_artifact(args.functional_inventory, root, "functional_inventory"))
    feature_sources.extend(functional_docs)
    feature_sources.extend(second_docs)
    feature_records, feature_ids = _feature_inventory(feature_sources, set(page_ids), issues)
    feature_records, feature_ids = _merge_feature_inventories(
        _planned_feature_inventory(root, issues),
        feature_records,
        issues,
    )
    page_metadata = _functional_page_metadata(feature_sources, set(page_ids), issues)

    first_outcomes = {entity: [] for entity in OUTCOME_KEYS}
    second_outcomes = {entity: [] for entity in OUTCOME_KEYS}
    all_outcomes = {entity: [] for entity in OUTCOME_KEYS}
    for phase, docs, destination in (
        ("first_pass", functional_docs, first_outcomes),
        ("second_pass", second_docs, second_outcomes),
    ):
        for path, payload in docs:
            relative_source = _relative(path, root)
            for entity in OUTCOME_KEYS:
                extracted = _extract_outcomes(
                    payload,
                    entity=entity,
                    source=relative_source,
                    phase=phase,
                    issues=issues,
                )
                destination[entity].extend(extracted)
                all_outcomes[entity].extend(extracted)
            raw_pages = _raw_playwright_page_outcomes(payload, source=relative_source, phase=phase)
            destination["page"].extend(raw_pages)
            all_outcomes["page"].extend(raw_pages)

    final_outcomes: dict[str, dict[str, dict[str, Any]]] = {}
    outcome_history: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for entity in OUTCOME_KEYS:
        final_outcomes[entity], outcome_history[entity] = _merge_outcomes(all_outcomes[entity])

    page_metrics = _coverage(page_ids, final_outcomes["page"], entity="page")
    interaction_metrics = _coverage(control_ids, final_outcomes["interaction"], entity="interaction")
    feature_metrics = _coverage(feature_ids, final_outcomes["feature"], entity="feature")
    for metric in (page_metrics, interaction_metrics, feature_metrics):
        if metric["unexpected_result_ids"]:
            issues.append({
                "code": "RESULT_ID_NOT_IN_FROZEN_INVENTORY",
                "entity": metric["entity"],
                "ids": metric["unexpected_result_ids"],
            })

    supplemental_docs: list[tuple[Path, Mapping[str, Any]]] = []
    explicit_supplemental = {path.resolve() for path in args.supplemental_evidence}
    supplemental_candidates: list[Path] = list(args.supplemental_evidence)
    discoverable = set(AUDIT_SPECS) | {
        "functional-bug-list.json",
        "frontend-data-label-scan.json",
        "ui-layout-freeze-report.json",
        "console-network-audit.json",
    }
    for filename in sorted(discoverable):
        stem = filename.removesuffix(".json")
        candidate = _first_existing((
            evidence_dir / filename,
            evidence_dir / f"{stem}.raw.json",
            evidence_dir / f"{stem}.source.json",
            evidence_dir / f"{stem}.playwright.json",
        ))
        if candidate and candidate.resolve() not in explicit_supplemental:
            supplemental_candidates.append(candidate)
            explicit_supplemental.add(candidate.resolve())
    for index, path in enumerate(supplemental_candidates):
        payload = _read_json(path, f"supplemental_{index + 1}", issues)
        if payload is not None:
            supplemental_docs.append((path, payload))
            inputs.append(_artifact(path, root, "supplemental"))
    supplemental_payloads = functional_docs + second_docs + supplemental_docs

    static_scan = _static_frontend_scan(frontend_dir, root)
    static_label_scan = _static_label_scan(frontend_dir, root)
    dom_label_scan = _extract_dom_label_audit(supplemental_payloads, root)
    runtime_status_contract = _runtime_global_status_contract(supplemental_payloads)
    if (
        static_label_scan["status"] == "FAIL"
        or dom_label_scan["status"] == "FAIL"
        or runtime_status_contract["status"] == "FAIL"
    ):
        combined_label_status = "FAIL"
    elif (
        static_label_scan["status"]
        == dom_label_scan["status"]
        == runtime_status_contract["status"]
        == "PASS"
    ):
        combined_label_status = "PASS"
    else:
        combined_label_status = "UNKNOWN"
    label_output = _base("day1_frontend_data_label_scan", combined_label_status) | {
        "static_scan": static_label_scan,
        "runtime_dom_scan": dom_label_scan,
        "runtime_global_data_status_contract": runtime_status_contract,
    }

    console_history_output = _console_audit(
        (console_path, console_payload) if console_payload is not None else None,
        supplemental_payloads,
        root,
    )
    console_output = _console_audit(None, second_docs + supplemental_docs, root)
    console_output["history"] = {
        "status": console_history_output["status"],
        "console_error_count": console_history_output["console_error_count"],
        "request_failure_count": console_history_output["request_failure_count"],
        "blocking_network_error_count": console_history_output["blocking_network_error_count"],
        "source_artifacts": console_history_output["source_artifacts"],
    }
    console_output["first_pass_source"] = _artifact(console_path, root, "console_first_pass") if console_payload is not None else None
    layout_output = _layout_report(page_records, second_docs + supplemental_docs, args.layout_tolerance_px)
    bug_output = _bugs(
        supplemental_payloads,
        control_records,
        interaction_metrics,
        static_scan,
        static_label_scan,
        root,
    )

    audit_outputs = {
        filename: _generic_audit(filename, keys, supplemental_payloads, root)
        for filename, keys in AUDIT_SPECS.items()
    }

    data_chain_path = args.data_chain_audit
    if data_chain_path is None:
        data_chain_path = _first_existing(evidence_dir / name for name in (
            "data-chain-audit.json",
            "data-chain-audit.raw.json",
            "data-chain-audit.source.json",
            "db-api-chain-audit.json",
            "db-api-frontend-chain.json",
            "frontend-data-chain-audit.json",
        ))
    data_chain_payload = None
    if data_chain_path is None:
        issues.append({"code": "MISSING_INPUT", "role": "data_chain_audit"})
    else:
        data_chain_payload = _read_json(data_chain_path, "data_chain_audit", issues)
        if data_chain_payload is not None:
            inputs.append(_artifact(data_chain_path, root, "data_chain_audit"))
    data_chain_status, data_chain_reason = _acceptance_status(data_chain_payload)

    runtime_path = args.runtime_cold_start
    if runtime_path is None:
        runtime_path = _first_existing((
            evidence_dir / "runtime-cold-start-report.json",
            evidence_dir / "runtime-cold-start.json",
            evidence_dir / "cold-start-report.json",
            root / "runtime" / "integration41full-startup-report.json",
        ))
    runtime_payload = None
    if runtime_path is None:
        issues.append({"code": "MISSING_INPUT", "role": "runtime_cold_start"})
    else:
        runtime_payload = _read_json(runtime_path, "runtime_cold_start", issues)
        if runtime_payload is not None:
            inputs.append(_artifact(runtime_path, root, "runtime_cold_start"))

    one_click_selected: tuple[Path, Any] | None = None
    second_start_selected: tuple[Path, Any] | None = None
    if args.one_click_evidence:
        payload = _read_json(args.one_click_evidence, "one_click_start", issues)
        if payload is not None:
            one_click_selected = (args.one_click_evidence, payload)
            inputs.append(_artifact(args.one_click_evidence, root, "one_click_start"))
    if args.second_start_evidence:
        payload = _read_json(args.second_start_evidence, "second_start", issues)
        if payload is not None:
            second_start_selected = (args.second_start_evidence, payload)
            inputs.append(_artifact(args.second_start_evidence, root, "second_start"))
    if runtime_payload is not None and runtime_path is not None:
        one_click_selected = one_click_selected or (runtime_path, _attempt_from_runtime(runtime_payload, 0))
        second_attempt = _attempt_from_runtime(runtime_payload, 1)
        if second_attempt is not None:
            second_start_selected = second_start_selected or (runtime_path, second_attempt)
    one_click_output = _startup_output("one_click_start", one_click_selected, root)
    second_start_output = _startup_output("second_start", second_start_selected, root)

    first_pass_output = _phase_result(
        "first_pass", page_ids, control_ids, feature_ids, first_outcomes, len(functional_docs),
    )
    second_pass_output = _phase_result(
        "second_pass", page_ids, control_ids, feature_ids, second_outcomes, len(second_docs),
    )

    route_status = "PASS" if page_ids and not any(issue["code"] in {
        "MISSING_STABLE_INVENTORY", "EMPTY_STABLE_INVENTORY", "DUPLICATE_STABLE_ID",
        "INVALID_STABLE_ID", "ROUTE_DENOMINATOR_MISMATCH",
    } and issue.get("entity", "page") == "page" for issue in issues) else "FAIL"
    route_output = _base("day1_route_inventory", route_status) | {
        "inventory_status": route_status,
        "page_state_denominator": len(page_ids),
        "stable_page_ids": page_ids,
        "functional_metrics": page_metrics,
        "page_states": [
            dict(page) | {
                "discovery_status": _status(page.get("status")),
                "functional_result": next((item for item in page_metrics["results"] if item["id"] == page["id"]), None),
            }
            for page in page_records
        ],
        "source_artifacts": [_artifact(route_path, root, "route_first_pass")] if route_payload is not None else [],
    }

    interaction_status = "PASS" if control_ids and not any(issue["code"] in {
        "MISSING_STABLE_INVENTORY", "EMPTY_STABLE_INVENTORY", "DUPLICATE_STABLE_ID",
        "INVALID_STABLE_ID", "INTERACTION_DENOMINATOR_MISMATCH",
    } and issue.get("entity", "interaction") == "interaction" for issue in issues) else "FAIL"
    result_by_control = {item["id"]: item for item in interaction_metrics["results"]}
    interaction_output = _base("day1_interaction_inventory", interaction_status) | {
        "inventory_status": interaction_status,
        "deduplicated_control_count": len(control_ids),
        "stable_control_ids": control_ids,
        "functional_metrics": interaction_metrics,
        "controls": [dict(control) | {"functional_result": result_by_control.get(control["id"])} for control in control_records],
        "source_artifacts": [_artifact(interaction_path, root, "interaction_first_pass")] if interaction_payload is not None else [],
    }

    result_by_feature = {item["id"]: item for item in feature_metrics["results"]}
    feature_inventory_status = "PASS" if feature_ids else "UNKNOWN"
    frontend_inventory_output = _base("day1_frontend_functional_inventory", feature_inventory_status) | {
        "inventory_status": feature_inventory_status,
        "page_stable_id_count": len(page_ids),
        "interaction_stable_id_count": len(control_ids),
        "user_visible_feature_denominator": len(feature_ids),
        "stable_feature_ids": feature_ids,
        "user_visible_feature_metrics": feature_metrics,
        "pages": [
            {
                "id": page["id"],
                "route": page_metadata.get(page["id"], {}).get("route", page.get("route")),
                "page_name": page_metadata.get(page["id"], {}).get("page_name", page_metadata.get(page["id"], {}).get("name", page.get("name"))),
                "visible": page_metadata.get(page["id"], {}).get("visible", _is_pass(_status(page.get("status")))),
                "auth_required": page_metadata.get(page["id"], {}).get("auth_required", page.get("auth_required")),
                "roles": page_metadata.get(page["id"], {}).get("roles", page.get("roles") if isinstance(page.get("roles"), list) else []),
                "roles_status": "DECLARED" if isinstance(page_metadata.get(page["id"], {}).get("roles", page.get("roles")), list) and page_metadata.get(page["id"], {}).get("roles", page.get("roles")) else "UNKNOWN",
                "parent": page_metadata.get(page["id"], {}).get("parent", page.get("parent")),
                "api_endpoints": page_metadata.get(page["id"], {}).get("api_endpoints", page.get("api_endpoints") if isinstance(page.get("api_endpoints"), list) else []),
                "control_ids": [str(control["id"]) for control in control_records if control.get("page_id") == page["id"]],
            }
            for page in page_records
        ],
        "features": [dict(feature) | {"functional_result": result_by_feature.get(feature["id"])} for feature in feature_records],
        "static_code_scan": static_scan,
        "denominator_rule": "only explicit frozen feature_inventory stable IDs; result-only IDs never enlarge or shrink the denominator",
    }

    outputs: dict[str, dict[str, Any]] = {
        "frontend-functional-inventory.json": frontend_inventory_output,
        "route-inventory.json": route_output,
        "interaction-inventory.json": interaction_output,
        "first-pass-results.json": first_pass_output,
        "functional-bug-list.json": bug_output,
        "console-network-audit.json": console_output,
        "frontend-data-label-scan.json": label_output,
        "ui-layout-freeze-report.json": layout_output,
        "second-pass-results.json": second_pass_output,
        "one-click-start.json": one_click_output,
        "second-start.json": second_start_output,
        **audit_outputs,
    }

    gate_sources = [(path, payload, "first_pass") for path, payload in functional_docs]
    gate_sources.extend((path, payload, "second_pass") for path, payload in second_docs)
    gate_sources.extend((path, payload, "supplemental") for path, payload in supplemental_docs)
    explicit_gates, gate_history = _extract_gates(gate_sources, root)
    gates = {name: explicit_gates.get(name, _gate_record("UNKNOWN", "no explicit or derived evidence", "builder")) for name in HARD_GATES}

    def derive_gate(name: str, decision: Mapping[str, Any]) -> None:
        explicit = explicit_gates.get(name)
        gates[name] = _combine_gate(explicit, decision) if explicit is not None else dict(decision)

    derive_gate("ALL_ROUTES_TESTED", _gate_record(
        "PASS" if page_metrics["acceptance_status"] == "PASS" else "FAIL",
        f"{page_metrics['covered']}/{page_metrics['denominator']} covered; {page_metrics['passed']} applicable PASS",
        "stable page inventory join",
    ))
    derive_gate("ALL_VISIBLE_FUNCTIONS_TESTED", _gate_record(
        "PASS" if feature_metrics["acceptance_status"] == "PASS" else "FAIL",
        f"{feature_metrics['passed']}/{feature_metrics['applicable_denominator']} applicable feature IDs PASS",
        "stable feature inventory join",
    ))
    button_ids = [str(control["id"]) for control in control_records if str(control.get("tag") or "").lower() == "button"]
    button_metrics = _coverage(button_ids, final_outcomes["interaction"], entity="button")
    derive_gate("ALL_BUTTONS", _gate_record(
        "PASS" if button_metrics["acceptance_status"] == "PASS" else "FAIL",
        f"{button_metrics['passed']}/{button_metrics['applicable_denominator']} applicable button IDs PASS",
        "stable interaction inventory join",
    ))
    derive_gate("NO_FRONTEND_MOCK", _gate_record(
        static_scan["mock_scan"]["status"],
        f"static findings={static_scan['mock_scan']['finding_count']}",
        "frontend/src static scan",
    ))
    derive_gate("NO_FRONTEND_DATA_SOURCE_LABEL", _gate_record(
        label_output["status"],
        "ordinary business static scan plus runtime DOM scan and global status contract",
        "frontend-data-label-scan.json",
    ))
    derive_gate("DB_API_FRONTEND_CHAIN", _gate_record(data_chain_status, data_chain_reason, "data-chain audit"))
    derive_gate("CONSOLE_ERRORS", _gate_record(
        "PASS" if console_output["status"] == "PASS" and console_output["console_error_count"] == 0 else console_output["status"],
        f"console/page errors={console_output['console_error_count']}",
        "console-network-audit.json",
    ))
    derive_gate("BLOCKING_NETWORK_ERRORS", _gate_record(
        "PASS" if console_output["status"] == "PASS" and console_output["blocking_network_error_count"] == 0 else console_output["status"],
        f"blocking network errors={console_output['blocking_network_error_count']}",
        "console-network-audit.json",
    ))
    derive_gate("UI_LAYOUT_UNCHANGED", _gate_record(layout_output["status"], "layout freeze comparison", "ui-layout-freeze-report.json"))
    derive_gate("ONE_CLICK_START", _gate_record(one_click_output["status"], one_click_output["reason"], "one-click-start.json"))
    derive_gate("SECOND_START", _gate_record(second_start_output["status"], second_start_output["reason"], "second-start.json"))
    derive_gate("PLAYWRIGHT", _gate_record(second_pass_output["status"], "complete stable-ID second pass", "second-pass-results.json"))

    audit_to_gate = {
        "kpi-audit.json": ("ALL_KPI_CARDS",),
        "chart-audit.json": ("ALL_CHARTS", "TREND_DATA"),
        "chatbi-audit.json": ("CHATBI",),
        "rag-audit.json": ("RAG",),
        "memory-audit.json": ("MEMORY",),
        "p6-audit.json": ("ALERT", "REPORT", "METRIC_GOVERNANCE"),
    }
    for filename, gate_names in audit_to_gate.items():
        audit = audit_outputs[filename]
        for gate_name in gate_names:
            if gates[gate_name]["status"] == "UNKNOWN":
                gates[gate_name] = _gate_record(audit["status"], f"derived from {filename}", filename)

    model_audit = audit_outputs["model-provider-audit.json"]
    submitted_model = model_audit.get("submitted_audit")
    if isinstance(submitted_model, dict):
        provider_gates = submitted_model.get("gates") or submitted_model.get("providers")
        if isinstance(provider_gates, dict):
            for gate_name in ("SQLBOT", "KIMI", "MIMO", "DEEPSEEK"):
                for key in (gate_name, gate_name.lower()):
                    if key in provider_gates and gates[gate_name]["status"] == "UNKNOWN":
                        raw = provider_gates[key]
                        if isinstance(raw, dict):
                            status, reason = _acceptance_status(raw)
                        else:
                            status, reason = _status(raw), "provider audit"
                        gates[gate_name] = _gate_record(status, reason, "model-provider-audit.json")
                        break

    blockers = list(issues)
    if static_scan["files_scanned"] == 0:
        blockers.append({"code": "FRONTEND_SOURCE_NOT_SCANNED", "path": str(frontend_dir)})
    for metric in (page_metrics, interaction_metrics, feature_metrics):
        if metric["acceptance_status"] != "PASS":
            blockers.append({
                "code": "STABLE_ID_ACCEPTANCE_INCOMPLETE",
                "entity": metric["entity"],
                "coverage_percent": metric["coverage_percent"],
                "pass_rate_percent": metric["pass_rate_percent"],
            })
    for name, decision in gates.items():
        status = _status(decision.get("status"))
        reason = str(decision.get("reason") or "")
        accepted = _is_pass(status) or (name in OPTIONAL_NA_GATES and _is_valid_na(status, reason))
        if not accepted:
            blockers.append({"code": "HARD_GATE_NOT_PASS", "gate": name, "status": status, "reason": reason})
    if bug_output["status"] != "PASS":
        blockers.append({"code": "FUNCTIONAL_BUG_LIST_NOT_CLOSED", "status": bug_output["status"], "unresolved": bug_output["unresolved"]})
    if data_chain_status != "PASS":
        blockers.append({"code": "DATA_CHAIN_NOT_PASS", "status": data_chain_status})
    if runtime_payload is None:
        blockers.append({"code": "RUNTIME_COLD_START_NOT_PROVIDED"})

    # Historical first-pass failures are allowed only when their stable IDs are
    # terminally resolved later.  Every other required final artifact must be
    # explicitly PASS; an UNKNOWN audit may never be hidden by a summary gate.
    for filename, payload in outputs.items():
        if filename == "first-pass-results.json":
            continue
        artifact_status = _status(payload.get("status"))
        if not _is_pass(artifact_status):
            blockers.append({
                "code": "REQUIRED_ARTIFACT_NOT_PASS",
                "artifact": filename,
                "status": artifact_status,
            })

    final_status = "PASS" if not blockers else "FAIL"
    headline = {
        "page_coverage_percent": page_metrics["coverage_percent"],
        "interactive_control_coverage_percent": interaction_metrics["coverage_percent"],
        "user_visible_function_pass_rate_percent": feature_metrics["pass_rate_percent"],
    }
    final_output = _base("day1_final_functional_acceptance", final_status) | {
        "DAY1_FUNCTIONAL_ACCEPTANCE": final_status,
        **headline,
        "headline_metrics": {
            "page_coverage": {
                "percent": headline["page_coverage_percent"],
                "numerator": page_metrics["covered"],
                "denominator": page_metrics["denominator"],
            },
            "interactive_control_coverage": {
                "percent": headline["interactive_control_coverage_percent"],
                "numerator": interaction_metrics["covered"],
                "denominator": interaction_metrics["denominator"],
            },
            "user_visible_function_pass_rate": {
                "percent": headline["user_visible_function_pass_rate_percent"],
                "numerator": feature_metrics["passed"],
                "denominator": feature_metrics["applicable_denominator"],
                "valid_not_applicable": feature_metrics["valid_not_applicable"],
            },
        },
        "coverage_calculation": {
            "page": page_metrics,
            "interaction": interaction_metrics,
            "user_visible_feature": feature_metrics,
            "rule": "coverage and pass rates come only from frozen stable-ID lists; summary counts are never trusted as denominators",
        },
        "hard_gates": gates,
        "gate_history": gate_history,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "inputs": inputs,
        "truth_boundary": {
            "missing_evidence_can_pass": False,
            "unknown_or_fail_can_pass": False,
            "not_applicable_requires_reason": True,
            "first_pass_visibility_is_functional_pass": False,
        },
    }
    outputs["final-functional-acceptance.json"] = final_output
    missing_outputs = sorted(set(FINAL_FILENAMES) - set(outputs))
    if missing_outputs:
        raise AssertionError(f"builder omitted required output(s): {missing_outputs}")
    return outputs, final_output, blockers


def _write_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    force: bool,
    preserve_external: bool = True,
) -> str:
    if path.exists() and not force:
        try:
            existing = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise RuntimeError(f"refusing to overwrite invalid existing evidence without --force: {path}")
        if not _is_generated(existing):
            if preserve_external:
                return "preserved_external"
            raise RuntimeError(f"refusing to leave a stale external final summary in place; use --force after review: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "written"


def _self_test() -> dict[str, Any]:
    tests = 0

    def check(condition: bool, message: str) -> None:
        nonlocal tests
        tests += 1
        if not condition:
            raise AssertionError(message)

    pages = ["PAGE-A", "PAGE-B"]
    outcomes = {
        "PAGE-A": {"status": "PASS", "reason": ""},
        "PAGE-B": {"status": "NOT_APPLICABLE", "reason": "OIDC-only state is disabled by deployment contract"},
    }
    metric = _coverage(pages, outcomes, entity="page")
    check(metric["coverage_percent"] == 100.0, "valid N/A must count as covered")
    check(metric["pass_rate_percent"] == 100.0, "valid N/A must be excluded from applicable pass-rate denominator")
    invalid = _coverage(["CONTROL-A"], {"CONTROL-A": {"status": "NOT_APPLICABLE", "reason": ""}}, entity="interaction")
    check(invalid["acceptance_status"] == "FAIL", "N/A without reason must fail closed")
    missing = _coverage(["FEATURE-A"], {}, entity="feature")
    check(missing["coverage_percent"] == 0.0 and missing["acceptance_status"] == "FAIL", "missing outcome must not pass")
    unexpected = _coverage(["FEATURE-A"], {"FEATURE-B": {"status": "PASS", "reason": ""}}, entity="feature")
    check(unexpected["unexpected_result_ids"] == ["FEATURE-B"], "unexpected IDs must be reported")
    check(_acceptance_status({"status": "PASS", "checks": {"a": True, "b": False}})[0] == "FAIL", "failed nested check must fail")
    check(_acceptance_status("NOT_APPLICABLE")[0] == "UNKNOWN", "scalar N/A must not invent a reason")
    check(_acceptance_status({"status": "NOT_APPLICABLE", "reason": "feature is absent by frozen product scope"})[0] == "NOT_APPLICABLE", "reasoned N/A must be retained")
    combined = _combine_gate(_gate_record("FAIL", "runtime failure", "playwright"), _gate_record("PASS", "static pass", "scan"))
    check(combined["status"] == "FAIL", "derived PASS must not override explicit FAIL")
    combined_unknown = _combine_gate(_gate_record("UNKNOWN", "runtime missing", "playwright"), _gate_record("PASS", "static pass", "scan"))
    check(combined_unknown["status"] == "UNKNOWN", "derived PASS must not override explicit UNKNOWN")
    check(_status("bug-fixed-pass") == "BUG_FIXED_PASS", "status normalization failed")
    check(set(FINAL_FILENAMES) == {
        "frontend-functional-inventory.json", "route-inventory.json", "interaction-inventory.json",
        "first-pass-results.json", "missing-data-matrix.json", "functional-bug-list.json",
        "data-seed-result.json", "kpi-audit.json", "chart-audit.json", "chatbi-audit.json",
        "model-provider-audit.json", "rag-audit.json", "memory-audit.json", "p6-audit.json",
        "console-network-audit.json", "frontend-data-label-scan.json", "ui-layout-freeze-report.json",
        "second-pass-results.json", "one-click-start.json", "second-start.json",
        "final-functional-acceptance.json",
    }, "required output set drifted")
    return {"status": "PASS", "tests": tests, "writes_performed": 0}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build fail-closed DAY-1 page/control/function acceptance JSON from stable-ID evidence.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "PASS rules:\n"
            "  * page/control/function denominators come only from frozen stable IDs;\n"
            "  * first-pass visibility is not a functional PASS;\n"
            "  * NOT_APPLICABLE requires a reason;\n"
            "  * missing, UNKNOWN, FAIL, duplicate, or unexpected IDs block final PASS;\n"
            "  * business-label scan excludes .global-data-status and governance/truth pages,\n"
            "    while the global region must show nature, time, source, and run_id.\n\n"
            "Use --dry-run to inspect the final decision without writing JSON.  Every command\n"
            "exits non-zero unless final acceptance is PASS."
        ),
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--evidence-dir", type=Path, help="Defaults to <repository-root>/docs/platformization/day1-functional-acceptance/evidence")
    parser.add_argument("--output-dir", type=Path, help="Defaults to --evidence-dir")
    parser.add_argument("--frontend-dir", type=Path, help="Defaults to <repository-root>/frontend/src")
    parser.add_argument("--route-first-pass", type=Path)
    parser.add_argument("--interaction-first-pass", type=Path)
    parser.add_argument("--console-first-pass", type=Path)
    parser.add_argument("--functional-inventory", type=Path, help="Frozen user-visible feature inventory JSON")
    parser.add_argument("--functional-evidence", type=Path, action="append", default=[], help="First-pass functional Playwright JSON; repeatable")
    parser.add_argument("--second-pass-evidence", type=Path, action="append", default=[], help="Second-pass functional Playwright JSON; repeatable")
    parser.add_argument("--supplemental-evidence", type=Path, action="append", default=[], help="Dedicated audit/gate JSON; repeatable")
    parser.add_argument("--runtime-cold-start", type=Path, help="Runtime report containing first and second startup attempts")
    parser.add_argument("--one-click-evidence", type=Path, help="Explicit first one-click startup evidence")
    parser.add_argument("--second-start-evidence", type=Path, help="Explicit idempotent second startup evidence")
    parser.add_argument("--data-chain-audit", type=Path, help="Database -> API -> frontend audit JSON")
    parser.add_argument("--layout-tolerance-px", type=float, default=4.0)
    parser.add_argument("--force", action="store_true", help="Overwrite externally generated final-path JSON; generated files are refreshed automatically")
    parser.add_argument("--dry-run", action="store_true", help="Do not write outputs; print final decision JSON")
    parser.add_argument("--self-test", action="store_true", help="Run in-memory unit self-checks; performs no filesystem writes")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(_self_test(), ensure_ascii=False, sort_keys=True))
        return 0
    root = args.repository_root.resolve()
    args.evidence_dir = _resolve(root, args.evidence_dir) if args.evidence_dir is not None else root / "docs" / "platformization" / "day1-functional-acceptance" / "evidence"
    args.output_dir = _resolve(root, args.output_dir) if args.output_dir is not None else args.evidence_dir
    args.frontend_dir = _resolve(root, args.frontend_dir) if args.frontend_dir is not None else root / "frontend" / "src"
    for attribute in (
        "route_first_pass", "interaction_first_pass",
        "console_first_pass", "functional_inventory", "runtime_cold_start", "one_click_evidence",
        "second_start_evidence", "data_chain_audit",
    ):
        value = getattr(args, attribute)
        if value is not None:
            setattr(args, attribute, _resolve(root, value))
    args.functional_evidence = [_resolve(root, path) for path in args.functional_evidence]
    args.second_pass_evidence = [_resolve(root, path) for path in args.second_pass_evidence]
    args.supplemental_evidence = [_resolve(root, path) for path in args.supplemental_evidence]
    if args.layout_tolerance_px < 0:
        parser.error("--layout-tolerance-px must be non-negative")

    outputs, final_output, blockers = _build(args)
    if args.dry_run:
        print(json.dumps(final_output, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        actions: dict[str, str] = {}
        # Final is written last so it can carry hashes for every other derived artifact.
        for filename in FINAL_FILENAMES:
            if filename == "final-functional-acceptance.json":
                continue
            actions[filename] = _write_json(args.output_dir / filename, outputs[filename], force=args.force)
        artifact_manifest: dict[str, Any] = {}
        for filename in FINAL_FILENAMES:
            if filename == "final-functional-acceptance.json":
                continue
            path = args.output_dir / filename
            if path.is_file():
                artifact_manifest[filename] = {
                    "path": _relative(path, root),
                    "sha256": _sha256(path),
                    "size": path.stat().st_size,
                }
            else:
                artifact_manifest[filename] = {
                    "payload_sha256": _payload_sha256(outputs[filename]),
                    "written": False,
                }
        final_output["artifacts"] = artifact_manifest
        actions["final-functional-acceptance.json"] = _write_json(
            args.output_dir / "final-functional-acceptance.json",
            final_output,
            force=args.force,
            preserve_external=False,
        )
        print(json.dumps({
            "status": final_output["status"],
            "page_coverage_percent": final_output["page_coverage_percent"],
            "interactive_control_coverage_percent": final_output["interactive_control_coverage_percent"],
            "user_visible_function_pass_rate_percent": final_output["user_visible_function_pass_rate_percent"],
            "blocker_count": len(blockers),
            "outputs": actions,
        }, ensure_ascii=False, sort_keys=True))
    if final_output["status"] == "PASS":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
