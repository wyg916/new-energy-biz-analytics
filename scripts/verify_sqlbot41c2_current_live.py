"""Read-only confirmation of the current DATA-4.1 SQLBot migration state."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "backend" / "alembic" / "versions"


def _literal_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    return None


def _heads() -> list[str]:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in VERSIONS.glob("*.py"):
        revision = _literal_assignment(path, "revision")
        down_revision = _literal_assignment(path, "down_revision")
        if isinstance(revision, str):
            revisions.add(revision)
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, (tuple, list)):
            parents.update(item for item in down_revision if isinstance(item, str))
    return sorted(revisions - parents)


def _database_state(container: str, database: str) -> dict:
    sql = """
    SELECT jsonb_build_object(
      'alembic_current', (SELECT version_num FROM alembic_version),
      'sales_semantic_version', (
        SELECT v.version FROM semantic_model_version v
        JOIN semantic_model m ON m.semantic_model_id=v.semantic_model_id
        WHERE m.scenario_id='sales_ops' AND v.status='ACTIVE'
      ),
      'sales_semantic_status', (
        SELECT v.status FROM semantic_model_version v
        JOIN semantic_model m ON m.semantic_model_id=v.semantic_model_id
        WHERE m.scenario_id='sales_ops' AND v.status='ACTIVE'
      ),
      'refund_amount_published', EXISTS (
        SELECT 1 FROM semantic_model_version v
        JOIN semantic_model m ON m.semantic_model_id=v.semantic_model_id
        JOIN semantic_table t ON t.semantic_model_version_id=v.semantic_model_version_id
        JOIN semantic_field f ON f.semantic_table_id=t.semantic_table_id
        WHERE m.scenario_id='sales_ops' AND v.status='ACTIVE'
          AND f.code='refund_amount'
      ),
      'category_alias_published', EXISTS (
        SELECT 1 FROM semantic_model_version v
        JOIN semantic_model m ON m.semantic_model_id=v.semantic_model_id
        JOIN dimension d ON d.semantic_model_version_id=v.semantic_model_version_id
        WHERE m.scenario_id='sales_ops' AND v.status='ACTIVE'
          AND d.code='category' AND d.aliases_json::jsonb ? '类别'
      ),
      'active_datasets', (
        SELECT jsonb_agg(jsonb_build_object(
          'scenario_id', d.scenario_id,
          'dataset_id', d.dataset_id,
          'dataset_version_id', v.dataset_version_id,
          'version', v.version,
          'source_version', v.source_version,
          'classification', d.data_classification,
          'period_start', v.period_start,
          'period_end_exclusive', v.period_end_exclusive
        ) ORDER BY d.scenario_id)
        FROM dataset_version v JOIN dataset d ON d.dataset_id=v.dataset_id
        JOIN semantic_activation a ON a.active_dataset_version_id=v.dataset_version_id
        WHERE v.status='ACTIVE'
      ),
      'active_source_bindings', (
        SELECT jsonb_agg(jsonb_build_object(
          'scenario_id', scenario_id,
          'datasource_id', datasource_id,
          'version', version,
          'execution_mode', binding_json::jsonb->>'execution_mode',
          'approved_relations', binding_json::jsonb->'approved_relations'
        ) ORDER BY scenario_id)
        FROM sqlbot_source_binding_release WHERE status='ACTIVE'
      )
    );
    """
    completed = subprocess.run(
        [
            "docker", "exec", container, "psql", "-U", "alpha", "-d", database,
            "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql,
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError("current migration query failed safely")
    return json.loads(completed.stdout.decode("utf-8").strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="renewable-data41-db-1")
    parser.add_argument("--database", default="renewable_p5b")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite evidence: {args.output}")
    state = _database_state(args.container, args.database)
    heads = _heads()
    datasets = state.get("active_datasets") or []
    bindings = state.get("active_source_bindings") or []
    checks = {
        "alembic_current": state.get("alembic_current") == "sqlbot_41c2",
        "single_alembic_head": heads == ["sqlbot_41c2"],
        "sales_semantic_1_0_1_active": (
            state.get("sales_semantic_version") == "1.0.1"
            and state.get("sales_semantic_status") == "ACTIVE"
        ),
        "refund_amount_published": state.get("refund_amount_published") is True,
        "category_alias_published": state.get("category_alias_published") is True,
        "current_data41_activations": (
            len(datasets) == 2
            and {item.get("scenario_id") for item in datasets}
            == {"charging_ops", "sales_ops"}
            and all(str(item.get("source_version", "")).startswith("DATA41-") for item in datasets)
        ),
        "single_active_binding_per_scenario": (
            len(bindings) == 2
            and {item.get("scenario_id") for item in bindings}
            == {"charging_ops", "sales_ops"}
            and all(item.get("execution_mode") == "upstream_readonly" for item in bindings)
        ),
    }
    report = {
        "evidence_type": "sqlbot41c2_current_live_migration",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "database": args.database,
        "database_container": args.container,
        "alembic_heads": heads,
        "checks": checks,
        "state": state,
        "read_only_verification": True,
        "secret_values_exposed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "checks": checks}, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
