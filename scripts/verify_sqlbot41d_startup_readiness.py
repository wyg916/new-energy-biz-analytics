"""Verify SQLBot 4.1D startup dependencies without exposing governed secrets."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.query_engines.router import CanaryPolicy, EngineMode, EngineRouter
from app.query_engines.sqlbot.source_binding import EXPECTED_BINDINGS


MODES = {"SHADOW", "CANARY_5", "CANARY_20", "SCOPED_STABLE"}


def _configuration(mode: str) -> dict:
    if mode == "CANARY_5":
        engine_mode, percentage = "CANARY", 5.0
    elif mode == "CANARY_20":
        engine_mode, percentage = "CANARY", 20.0
    elif mode == "SCOPED_STABLE":
        engine_mode, percentage = "SCOPED_STABLE", 100.0
    else:
        engine_mode, percentage = "SHADOW", 0.0
    return {
        "startup_mode": mode,
        "query_engine_mode": engine_mode,
        "canary_percentage": percentage,
        "activation_source": "SQLBOT_41D_MODE controlled environment variable",
        "business_api_startup_mode": "SHADOW",
        "controlled_acceptance_mode": mode,
        "business_api_global_sqlbot_activated": False,
        "controlled_mode_requires_all_four_allowlists": mode != "SHADOW",
        "default_is_global_stable": False,
        "tenant_allowlist_required": mode != "SHADOW",
        "workspace_allowlist_required": mode != "SHADOW",
        "user_allowlist_required": mode != "SHADOW",
        "scenario_allowlist": ["charging_ops", "sales_ops"],
    }


def _router_ready(mode: str) -> bool:
    engine_mode = {
        "SHADOW": EngineMode.SHADOW,
        "CANARY_5": EngineMode.CANARY,
        "CANARY_20": EngineMode.CANARY,
        "SCOPED_STABLE": EngineMode.SCOPED_STABLE,
    }[mode]
    percentage = _configuration(mode)["canary_percentage"]
    policy = CanaryPolicy(
        percentage=percentage,
        tenants=frozenset({"tenant-alpha"}) if mode != "SHADOW" else frozenset(),
        workspaces=(
            frozenset({"workspace-alpha"}) if mode != "SHADOW" else frozenset()
        ),
        users=frozenset({"startup-probe"}) if mode != "SHADOW" else frozenset(),
        scenarios=frozenset(EXPECTED_BINDINGS) if mode != "SHADOW" else frozenset(),
    )
    router = EngineRouter(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        mode=engine_mode,
        canary=policy,
        fallback_enabled=True,
    )
    return router.mode == engine_mode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", default="SHADOW", choices=sorted(MODES))
    parser.add_argument("--expected-revision", default="sqlbot_41c2")
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite evidence: {args.output}")

    with SessionLocal() as db:
        database_state = db.execute(text("""
            SELECT jsonb_build_object(
              'migration', (SELECT version_num FROM alembic_version),
              'credential_reference_count', (
                SELECT COUNT(*) FROM credential_reference
                WHERE reference_name IN (
                  'preprod-sqlbot-username', 'preprod-sqlbot-password'
                ) AND status = 'ACTIVE'
              ),
              'charging_view_count', (
                SELECT COUNT(*) FROM information_schema.views
                WHERE table_schema = 'semantic_sqlbot_charging'
              ),
              'sales_view_count', (
                SELECT COUNT(*) FROM information_schema.views
                WHERE table_schema = 'semantic_sqlbot_sales'
              ),
              'active_binding_count', (
                SELECT COUNT(*) FROM sqlbot_source_binding_release
                WHERE status = 'ACTIVE'
              ),
              'binding_relation_counts', (
                SELECT jsonb_object_agg(
                  scenario_id,
                  jsonb_array_length(binding_json::jsonb->'approved_relations')
                )
                FROM sqlbot_source_binding_release WHERE status = 'ACTIVE'
              )
            )
        """)).scalar_one()

    runtime_file = Path(
        "/run/p4-runtime/sqlbot41b_readonly_credentials.json"
    )
    readonly_payload = json.loads(runtime_file.read_text(encoding="utf-8"))
    readonly_ready = all(
        isinstance(readonly_payload.get(scenario), dict)
        and bool(readonly_payload[scenario].get("role"))
        and bool(readonly_payload[scenario].get("password"))
        for scenario in EXPECTED_BINDINGS
    )
    readonly_roles = [
        str(readonly_payload[scenario]["role"])
        for scenario in EXPECTED_BINDINGS
        if isinstance(readonly_payload.get(scenario), dict)
        and readonly_payload[scenario].get("role")
    ]
    readonly_role_count = 0
    if len(readonly_roles) == len(EXPECTED_BINDINGS):
        with SessionLocal() as db:
            readonly_role_count = int(db.execute(text("""
                SELECT COUNT(*) FROM pg_roles
                WHERE rolname IN (:charging_role, :sales_role)
                  AND rolcanlogin = true
                  AND rolsuper = false
                  AND rolcreatedb = false
                  AND rolcreaterole = false
            """), {
                "charging_role": readonly_roles[0],
                "sales_role": readonly_roles[1],
            }).scalar_one())
    redis_ready = bool(Redis.from_url(get_settings().redis_url).ping())
    relation_counts = database_state.get("binding_relation_counts") or {}
    checks = {
        "postgresql_ready": database_state.get("migration") == args.expected_revision,
        "credential_reference_ready": (
            database_state.get("credential_reference_count") == 2
        ),
        "readonly_roles_ready": readonly_ready and readonly_role_count == 2,
        "semantic_views_6_10": (
            database_state.get("charging_view_count") == 6
            and database_state.get("sales_view_count") == 10
        ),
        "data41_binding_ready": (
            database_state.get("active_binding_count") == 2
            and relation_counts == {"charging_ops": 6, "sales_ops": 10}
        ),
        "redis_ready": redis_ready,
        "router_configuration_visible": _router_ready(args.mode),
        "safe_default": args.mode != "SHADOW" or _configuration(args.mode)[
            "query_engine_mode"
        ] == "SHADOW",
    }
    report = {
        "schema_version": "1.0",
        "evidence_type": "sqlbot41d_startup_readiness",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "runtime": {
            "migration": database_state.get("migration"),
            "expected_migration": args.expected_revision,
            "credential_reference_count": database_state.get(
                "credential_reference_count"
            ),
            "readonly_role_count": readonly_role_count,
            "semantic_view_counts": {
                "charging_ops": database_state.get("charging_view_count"),
                "sales_ops": database_state.get("sales_view_count"),
            },
            "active_binding_count": database_state.get("active_binding_count"),
            "binding_relation_counts": relation_counts,
        },
        "canary_configuration": _configuration(args.mode),
        "secret_values_persisted": False,
        "truth_boundary": {
            "production_traffic_claimed": False,
            "real_customer_usage_claimed": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "checks": checks}))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
