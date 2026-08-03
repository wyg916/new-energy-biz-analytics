"""Create a new P5A backup and reconcile it in one isolated temporary database."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


RESTORE_NAME = re.compile(r"^p5[ab]_restore_verify_[a-z0-9_]{4,40}$")

INNER_SCRIPT = r'''
set -eu
restore_db="$1"
stamp="$2"
source_db="$3"
file_prefix="$4"
backup_file="/backups/$file_prefix-acceptance-$stamp.dump"
case "$restore_db" in
  p5a_restore_verify_*|p5b_restore_verify_*) ;;
  *) echo "refusing unexpected restore database" >&2; exit 2 ;;
esac
export PGPASSWORD="$(sed -n '1p' /run/p4-runtime/postgres_password)"
test -n "$PGPASSWORD"
exists="$(psql -h db -U alpha -d postgres -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_database WHERE datname = '$restore_db'")"
test "$exists" = "0"
cleanup() {
  dropdb -h db -U alpha --if-exists "$restore_db" >/dev/null 2>&1 || true
}
trap cleanup EXIT
pg_dump -h db -U alpha -d "$source_db" --format=custom --no-owner --file="$backup_file"
backup_sha256="$(sha256sum "$backup_file" | sed 's/ .*//')"
backup_size_bytes="$(wc -c < "$backup_file" | tr -d ' ')"
createdb -h db -U alpha "$restore_db"
pg_restore -h db -U alpha -d "$restore_db" --no-owner --exit-on-error "$backup_file"
summary_sql="SELECT json_build_object(
  'alembic_revision',(SELECT version_num FROM alembic_version),
  'charging_sessions',(SELECT count(*) FROM fact_charging_session),
  'sales_orders',(SELECT count(*) FROM sales_order),
  'sales_order_items',(SELECT count(*) FROM sales_order_item),
  'metric_definitions',(SELECT count(*) FROM metric_definition),
  'published_metrics',(SELECT count(*) FROM metric),
  'credential_references',(SELECT count(*) FROM credential_reference),
  'credential_plaintext_columns',(SELECT count(*) FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'credential_reference'
      AND column_name IN ('password','token','secret_value','credential_value','private_key')),
  'credential_forbidden_metadata_rows',(SELECT count(*) FROM credential_reference
    WHERE metadata_json::text ~* '\"[^\"]*(password|token|secret_value|credential_value|private_key)[^\"]*\"[[:space:]]*:'),
  'memory_records',(SELECT count(*) FROM memory_record),
  'memory_audit_events',(SELECT count(*) FROM memory_audit_event),
  'governance_audit_events',(SELECT count(*) FROM governance_audit_event),
  'security_alerts',(SELECT count(*) FROM security_alert),
  'legal_holds',(SELECT count(*) FROM legal_hold),
  'platform_releases',(SELECT count(*) FROM platform_release),
  'release_registry_records',(SELECT count(*) FROM release_record),
  'production_gates',(SELECT count(*) FROM production_gate_registry),
  'production_gate_history',(SELECT count(*) FROM production_gate_history),
  'preproduction_acceptance_records',(SELECT count(*) FROM preproduction_acceptance_record),
  'datasource_governance_records',(SELECT count(*) FROM preproduction_datasource_governance)
)::text"
hash_sql="SELECT md5(string_agg(name || ':' || row_count || ':' || row_hash, '|' ORDER BY name))
FROM (
  SELECT 'fact_charging_session' name, count(*)::text row_count,
         coalesce(sum(hashtextextended(row_to_json(t)::text, 0)::numeric),0)::text row_hash FROM fact_charging_session t
  UNION ALL
  SELECT 'sales_order', count(*)::text,
         coalesce(sum(hashtextextended(row_to_json(t)::text, 0)::numeric),0)::text FROM sales_order t
  UNION ALL
  SELECT 'sales_order_item', count(*)::text,
         coalesce(sum(hashtextextended(row_to_json(t)::text, 0)::numeric),0)::text FROM sales_order_item t
) checks"
source_summary="$(psql -h db -U alpha -d "$source_db" -At -v ON_ERROR_STOP=1 -c "$summary_sql")"
restore_summary="$(psql -h db -U alpha -d "$restore_db" -At -v ON_ERROR_STOP=1 -c "$summary_sql")"
source_hash="$(psql -h db -U alpha -d "$source_db" -At -v ON_ERROR_STOP=1 -c "$hash_sql")"
restore_hash="$(psql -h db -U alpha -d "$restore_db" -At -v ON_ERROR_STOP=1 -c "$hash_sql")"
test "$source_summary" = "$restore_summary"
test "$source_hash" = "$restore_hash"
test "$(printf '%s' "$source_summary" | sed -n 's/.*\"credential_plaintext_columns\"[ ]*:[ ]*\([0-9][0-9]*\).*/\1/p')" = "0"
test "$(printf '%s' "$source_summary" | sed -n 's/.*\"credential_forbidden_metadata_rows\"[ ]*:[ ]*\([0-9][0-9]*\).*/\1/p')" = "0"
cleanup
trap - EXIT
printf '{"status":"PASS","backup_file":"%s","backup_sha256":"%s","backup_size_bytes":%s,"source_summary":%s,"restore_summary":%s,"source_data_hash":"%s","restore_data_hash":"%s","summary_equal":true,"data_hash_equal":true,"credential_plaintext_contract_passed":true,"legal_hold_reconciled":true,"restore_database_removed":true,"existing_volume_deleted":false,"secret_values_printed":false}\n' \
  "$backup_file" "$backup_sha256" "$backup_size_bytes" "$source_summary" "$restore_summary" "$source_hash" "$restore_hash"
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="renewable-p5a-remediation-backup-1")
    parser.add_argument("--restore-database", default="p5a_restore_verify_20260802")
    parser.add_argument("--source-database", default="renewable_p5a")
    parser.add_argument("--scope", choices=("p5a", "p5b"), default="p5a")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not RESTORE_NAME.fullmatch(args.restore_database):
        parser.error("restore database must use the p5a_restore_verify_ or p5b_restore_verify_ prefix")
    if not re.fullmatch(r"renewable_p5[ab]", args.source_database):
        parser.error("source database must be the isolated renewable_p5a or renewable_p5b database")
    if not args.restore_database.startswith(f"{args.scope}_restore_verify_"):
        parser.error("restore database prefix must match scope")
    if args.source_database != f"renewable_{args.scope}":
        parser.error("source database must match scope")
    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    process = subprocess.run(
        [
            "docker", "exec", "-i", args.container, "sh", "-s", "--",
            args.restore_database, stamp, args.source_database, args.scope,
        ],
        input=INNER_SCRIPT.replace("\r\n", "\n").encode("utf-8"),
        capture_output=True,
    )
    if process.returncode:
        if process.stderr:
            print(process.stderr.decode("utf-8", errors="replace"), end="")
        raise SystemExit(process.returncode)
    payload = json.loads(process.stdout.decode("utf-8"))
    payload.update({
        "evidence_type": f"{args.scope}_backup_restore_drill",
        "started_at": started_at.isoformat(),
        "executed_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "environment": f"{args.scope.upper()} production-acceptance, not production",
        "data_classification": "simulated",
        "source_database_modified": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
    })
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(serialized.encode("utf-8"))
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if payload.get("status") == "PASS" else 1)


if __name__ == "__main__":
    main()
