"""Create a P4 logical backup and verify it in one isolated temporary database."""

from __future__ import annotations

import argparse
import json
import re
import subprocess


RESTORE_NAME = re.compile(r"^p4_restore_verify_[a-z0-9_]{4,40}$")

INNER_SCRIPT = r'''
set -eu
restore_db="$1"
backup_file="/backups/p4-acceptance.dump"
case "$restore_db" in
  p4_restore_verify_*) ;;
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
pg_dump -h db -U alpha -d renewable_p4 --format=custom --no-owner --file="$backup_file"
backup_sha256="$(sha256sum "$backup_file" | sed 's/ .*//')"
createdb -h db -U alpha "$restore_db"
pg_restore -h db -U alpha -d "$restore_db" --no-owner --exit-on-error "$backup_file"
summary_sql="SELECT json_build_object(
  'charging_sessions',(SELECT count(*) FROM fact_charging_session),
  'sales_orders',(SELECT count(*) FROM sales_order),
  'sales_order_items',(SELECT count(*) FROM sales_order_item),
  'metric_definitions',(SELECT count(*) FROM metric_definition),
  'published_metrics',(SELECT count(*) FROM metric),
  'credential_references',(SELECT count(*) FROM credential_reference),
  'acceptance_records',(SELECT count(*) FROM preproduction_acceptance_record),
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
source_summary="$(psql -h db -U alpha -d renewable_p4 -At -v ON_ERROR_STOP=1 -c "$summary_sql")"
restore_summary="$(psql -h db -U alpha -d "$restore_db" -At -v ON_ERROR_STOP=1 -c "$summary_sql")"
source_hash="$(psql -h db -U alpha -d renewable_p4 -At -v ON_ERROR_STOP=1 -c "$hash_sql")"
restore_hash="$(psql -h db -U alpha -d "$restore_db" -At -v ON_ERROR_STOP=1 -c "$hash_sql")"
test "$source_summary" = "$restore_summary"
test "$source_hash" = "$restore_hash"
cleanup
trap - EXIT
printf '{"status":"PASS","backup_file":"%s","backup_sha256":"%s","source_summary":%s,"restore_summary":%s,"data_hash":"%s","summary_equal":true,"data_hash_equal":true,"restore_database_removed":true,"existing_volume_deleted":false,"secret_values_printed":false}\n' \
  "$backup_file" "$backup_sha256" "$source_summary" "$restore_summary" "$source_hash"
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="renewable-p4-rc-backup-1")
    parser.add_argument("--restore-database", default="p4_restore_verify_20260801")
    args = parser.parse_args()
    if not RESTORE_NAME.fullmatch(args.restore_database):
        parser.error("restore database must use the p4_restore_verify_ prefix")
    process = subprocess.run(
        ["docker", "exec", "-i", args.container, "sh", "-s", "--", args.restore_database],
        input=INNER_SCRIPT.replace("\r\n", "\n").encode("utf-8"),
        capture_output=True,
    )
    if process.returncode:
        if process.stderr:
            print(process.stderr.decode("utf-8", errors="replace"), end="")
        raise SystemExit(process.returncode)
    payload = json.loads(process.stdout.decode("utf-8"))
    if payload.get("status") != "PASS":
        raise SystemExit("backup restore verification did not pass")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
