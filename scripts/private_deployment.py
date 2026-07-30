"""Private single-customer deployment operations.

The commands deliberately avoid printing expanded Compose configuration,
connection URLs, passwords, or certificate private keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE_FILE = ROOT / "deploy" / "private" / "docker-compose.private.yml"
DEFAULT_ENV_FILE = ROOT / "deploy" / "private" / "private.env"
PLACEHOLDER_MARKERS = ("replace-with", "change-me", "alpha-local-only")
SAFE_SCHEMA = re.compile(r"^rc_restore_[a-z0-9_]{8,48}$")
RELEASE_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-rc\d+)?$")


class OperationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise OperationError(f"environment file not found: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def write_json(path: Path | None, payload: dict) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


class PrivateDeployment:
    def __init__(self, compose_file: Path, env_file: Path, project_name: str):
        self.compose_file = compose_file.resolve()
        self.env_file = env_file.resolve()
        self.project_name = project_name
        self.env = load_env(self.env_file)

    def compose_command(self, *arguments: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--project-name",
            self.project_name,
            "--env-file",
            str(self.env_file),
            "-f",
            str(self.compose_file),
            *arguments,
        ]

    def run(
        self,
        *arguments: str,
        capture_output: bool = True,
        text: bool = True,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            self.compose_command(*arguments),
            cwd=ROOT,
            capture_output=capture_output,
            text=text,
            encoding="utf-8" if text else None,
            check=check,
        )

    def preflight(self) -> dict:
        required = {
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "DATABASE_URL",
            "SECRET_KEY",
            "PUBLIC_BASE_URL",
            "CORS_ORIGINS",
            "TRUSTED_HOSTS",
            "RELEASE_VERSION",
            "TLS_DIR",
        }
        missing = sorted(key for key in required if not self.env.get(key))
        if missing:
            raise OperationError(f"required environment values missing: {', '.join(missing)}")

        sensitive_values = {
            "POSTGRES_PASSWORD": self.env["POSTGRES_PASSWORD"],
            "SECRET_KEY": self.env["SECRET_KEY"],
        }
        for key, value in sensitive_values.items():
            if any(marker in value.lower() for marker in PLACEHOLDER_MARKERS):
                raise OperationError(f"{key} still contains a placeholder")
        if len(self.env["POSTGRES_PASSWORD"]) < 16:
            raise OperationError("POSTGRES_PASSWORD must contain at least 16 characters")
        if len(self.env["SECRET_KEY"]) < 32:
            raise OperationError("SECRET_KEY must contain at least 32 characters")

        database_url = urlparse(self.env["DATABASE_URL"].replace("postgresql+psycopg", "postgresql", 1))
        if database_url.scheme != "postgresql" or not database_url.password:
            raise OperationError("DATABASE_URL must be a password-protected PostgreSQL URL")
        if unquote(database_url.password) != self.env["POSTGRES_PASSWORD"]:
            raise OperationError("DATABASE_URL password does not match POSTGRES_PASSWORD")
        if database_url.username != self.env["POSTGRES_USER"]:
            raise OperationError("DATABASE_URL user does not match POSTGRES_USER")
        if database_url.path.lstrip("/") != self.env["POSTGRES_DB"]:
            raise OperationError("DATABASE_URL database does not match POSTGRES_DB")

        public_url = urlparse(self.env["PUBLIC_BASE_URL"])
        if public_url.scheme != "https" or not public_url.hostname:
            raise OperationError("PUBLIC_BASE_URL must be an HTTPS URL")
        trusted_hosts = {item.strip().lower() for item in self.env["TRUSTED_HOSTS"].split(",") if item.strip()}
        if "*" in trusted_hosts or public_url.hostname.lower() not in trusted_hosts:
            raise OperationError("TRUSTED_HOSTS must explicitly contain the public host and no wildcard")
        origins = [item.strip() for item in self.env["CORS_ORIGINS"].split(",") if item.strip()]
        if not origins or any(not item.startswith("https://") for item in origins):
            raise OperationError("CORS_ORIGINS must contain HTTPS origins only")
        if not RELEASE_VERSION.fullmatch(self.env["RELEASE_VERSION"]):
            raise OperationError("RELEASE_VERSION must use x.y.z or x.y.z-rcN")

        tls_directory = Path(self.env["TLS_DIR"])
        if not tls_directory.is_absolute():
            tls_directory = (self.compose_file.parent / tls_directory).resolve()
        certificate = tls_directory / "tls.crt"
        private_key = tls_directory / "tls.key"
        if not certificate.is_file() or not private_key.is_file():
            raise OperationError("TLS_DIR must contain tls.crt and tls.key")

        subprocess.run(
            ["docker", "compose", "version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        self.run("config", "--quiet")
        expanded = json.loads(self.run("config", "--format", "json").stdout)
        services = expanded["services"]
        if services["db"].get("ports") or services["api"].get("ports"):
            raise OperationError("database and API services must not publish host ports")
        api_environment = services["api"]["environment"]
        if api_environment.get("APP_ENV") != "production":
            raise OperationError("private API must run with APP_ENV=production")
        if str(api_environment.get("AUTO_BOOTSTRAP_DEMO_USERS", "")).lower() != "false":
            raise OperationError("private API must disable demo user bootstrap")
        if str(api_environment.get("SIMULATED_DATA_ONLY", "")).lower() != "true":
            raise OperationError("release candidate must keep the simulated-data boundary")

        return {
            "status": "passed",
            "checked_at": utc_now(),
            "release_version": self.env["RELEASE_VERSION"],
            "public_host": public_url.hostname,
            "expected_database_revision": self.env.get("EXPECTED_DATABASE_REVISION", "0012"),
            "tls_certificate_present": True,
            "tls_private_key_present": True,
            "database_port_private": True,
            "api_port_private": True,
            "production_fail_closed": True,
            "simulated_data_only": True,
        }

    def database_identity(self) -> tuple[str, str]:
        process = self.run(
            "exec",
            "-T",
            "db",
            "sh",
            "-lc",
            'printf "%s\\n%s\\n" "$POSTGRES_USER" "$POSTGRES_DB"',
        )
        lines = [line for line in process.stdout.splitlines() if line]
        if len(lines) != 2:
            raise OperationError("could not resolve database identity from the running container")
        return lines[0], lines[1]

    def psql(self, sql: str, *, user: str, database: str) -> str:
        process = self.run(
            "exec",
            "-T",
            "db",
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            user,
            "-d",
            database,
            "-At",
            "-F",
            "\t",
            "-c",
            sql,
        )
        return process.stdout.strip()

    def table_counts(self, schema: str, *, user: str, database: str) -> dict[str, int]:
        tables_output = self.psql(
            "SELECT tablename FROM pg_tables "
            f"WHERE schemaname = '{schema}' ORDER BY tablename",
            user=user,
            database=database,
        )
        tables = [line.strip() for line in tables_output.splitlines() if line.strip()]
        if not tables:
            return {}
        quoted_schema = '"' + schema.replace('"', '""') + '"'
        queries = []
        for table in tables:
            quoted_table = '"' + table.replace('"', '""') + '"'
            literal_table = table.replace("'", "''")
            queries.append(
                f"SELECT '{literal_table}', count(*)::text FROM {quoted_schema}.{quoted_table}"
            )
        output = self.psql(" UNION ALL ".join(queries), user=user, database=database)
        counts: dict[str, int] = {}
        for line in output.splitlines():
            table, count = line.split("\t", 1)
            counts[table] = int(count)
        return counts

    def business_fingerprint(self, schema: str, *, user: str, database: str) -> dict[str, str]:
        quoted_schema = '"' + schema.replace('"', '""') + '"'
        queries = {
            "charging_session": (
                "SELECT concat_ws('|', count(*), "
                "coalesce(sum(energy_kwh), 0), "
                "coalesce(sum(electricity_fee_net_amount), 0), "
                "coalesce(sum(service_fee_net_amount), 0)) "
                f"FROM {quoted_schema}.fact_charging_session"
            ),
            "published_snapshot": (
                "SELECT concat_ws('|', count(*), "
                "coalesce(md5(string_agg(snapshot_checksum, '' ORDER BY station_id)), md5(''))) "
                f"FROM {quoted_schema}.published_station_snapshot"
            ),
            "scenario_release": (
                "SELECT concat_ws('|', count(*), "
                "coalesce(md5(string_agg(manifest_checksum, '' ORDER BY scenario_id, version)), md5(''))) "
                f"FROM {quoted_schema}.scenario_package_release"
            ),
        }
        return {
            name: self.psql(sql, user=user, database=database)
            for name, sql in queries.items()
        }

    def backup(self, output_directory: Path) -> dict:
        self.preflight()
        output_directory.mkdir(parents=True, exist_ok=True)
        user, database = self.database_identity()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = output_directory / f"{database}-{self.env['RELEASE_VERSION']}-{timestamp}.backup"
        command = self.compose_command(
            "exec",
            "-T",
            "db",
            "pg_dump",
            "-U",
            user,
            "-d",
            database,
            "-Fc",
            "--no-owner",
            "--no-privileges",
        )
        with backup_path.open("wb") as destination:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=destination,
                stderr=subprocess.PIPE,
            )
            _, stderr = process.communicate()
        if process.returncode != 0:
            raise OperationError(f"pg_dump failed with exit code {process.returncode}")

        table_counts = self.table_counts("public", user=user, database=database)
        fingerprint = self.business_fingerprint("public", user=user, database=database)
        revision = self.psql(
            "SELECT version_num FROM alembic_version",
            user=user,
            database=database,
        )
        manifest = {
            "status": "completed",
            "created_at": utc_now(),
            "release_version": self.env["RELEASE_VERSION"],
            "data_classification": "simulated",
            "database": database,
            "schema": "public",
            "alembic_revision": revision,
            "format": "postgresql-custom",
            "backup_file": backup_path.name,
            "size_bytes": backup_path.stat().st_size,
            "sha256": sha256_file(backup_path),
            "table_counts": table_counts,
            "business_fingerprint": fingerprint,
            "credential_material_in_manifest": False,
        }
        manifest_path = backup_path.with_suffix(".manifest.json")
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            **manifest,
            "backup_path": str(backup_path),
            "manifest_path": str(manifest_path),
        }

    @staticmethod
    def transform_restore_stream(source, destination, schema: str) -> None:
        replacement = f'"{schema}".'.encode()
        in_copy = False
        for line in iter(source.readline, b""):
            if in_copy:
                destination.write(line)
                if line.rstrip(b"\r\n") == b"\\.":
                    in_copy = False
                continue
            if line.startswith(b"COPY public."):
                in_copy = True
            destination.write(line.replace(b"public.", replacement))

    def restore_drill(self, backup_path: Path, manifest_path: Path) -> dict:
        self.preflight()
        if not backup_path.is_file() or not manifest_path.is_file():
            raise OperationError("backup and manifest files are required")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if backup_path.stat().st_size != manifest.get("size_bytes"):
            raise OperationError("backup size does not match manifest")
        if sha256_file(backup_path) != manifest.get("sha256"):
            raise OperationError("backup SHA-256 does not match manifest")

        user, database = self.database_identity()
        schema = f"rc_restore_{datetime.now(UTC).strftime('%m%d%H%M%S')}_{uuid4().hex[:8]}"
        if not SAFE_SCHEMA.fullmatch(schema):
            raise OperationError("generated restore schema is unsafe")
        container_backup = f"/tmp/{schema}.backup"
        schema_created = False
        restored_counts: dict[str, int] = {}
        restored_fingerprint: dict[str, str] = {}
        try:
            self.run("cp", str(backup_path.resolve()), f"db:{container_backup}")
            exists = self.psql(
                f"SELECT 1 FROM information_schema.schemata WHERE schema_name = '{schema}'",
                user=user,
                database=database,
            )
            if exists:
                raise OperationError("refusing to reuse an existing restore schema")
            self.psql(f'CREATE SCHEMA "{schema}"', user=user, database=database)
            schema_created = True

            source_process = subprocess.Popen(
                self.compose_command(
                    "exec",
                    "-T",
                    "db",
                    "pg_restore",
                    "--no-owner",
                    "--no-privileges",
                    "-f",
                    "-",
                    container_backup,
                ),
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            destination_process = subprocess.Popen(
                self.compose_command(
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-X",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-U",
                    user,
                    "-d",
                    database,
                ),
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert source_process.stdout is not None
            assert destination_process.stdin is not None
            self.transform_restore_stream(
                source_process.stdout,
                destination_process.stdin,
                schema,
            )
            destination_process.stdin.close()
            source_stderr = source_process.stderr.read() if source_process.stderr else b""
            destination_stdout = (
                destination_process.stdout.read() if destination_process.stdout else b""
            )
            destination_stderr = (
                destination_process.stderr.read() if destination_process.stderr else b""
            )
            source_process.wait()
            destination_process.wait()
            if source_process.returncode != 0:
                raise OperationError(
                    f"pg_restore stream failed with exit code {source_process.returncode}"
                )
            if destination_process.returncode != 0:
                raise OperationError(
                    f"restore psql failed with exit code {destination_process.returncode}"
                )
            _ = (source_stderr, destination_stdout, destination_stderr)

            restored_counts = self.table_counts(schema, user=user, database=database)
            restored_fingerprint = self.business_fingerprint(
                schema,
                user=user,
                database=database,
            )
            counts_match = restored_counts == manifest.get("table_counts")
            fingerprint_match = restored_fingerprint == manifest.get("business_fingerprint")
            revision_match = (
                self.psql(
                    f'SELECT version_num FROM "{schema}".alembic_version',
                    user=user,
                    database=database,
                )
                == manifest.get("alembic_revision")
            )
            if not counts_match or not fingerprint_match or not revision_match:
                raise OperationError("restored data does not reconcile with the backup manifest")
        finally:
            if schema_created:
                self.psql(f'DROP SCHEMA "{schema}" CASCADE', user=user, database=database)
            self.run(
                "exec",
                "-T",
                "db",
                "rm",
                "-f",
                container_backup,
                capture_output=True,
                check=False,
            )

        schema_removed = not bool(
            self.psql(
                f"SELECT 1 FROM information_schema.schemata WHERE schema_name = '{schema}'",
                user=user,
                database=database,
            )
        )
        return {
            "status": "passed",
            "executed_at": utc_now(),
            "isolation": "dedicated_schema",
            "restore_schema": schema,
            "backup_sha256": manifest["sha256"],
            "alembic_revision": manifest["alembic_revision"],
            "table_count": len(restored_counts),
            "row_count_total": sum(restored_counts.values()),
            "table_counts_match": True,
            "business_fingerprint_match": True,
            "revision_match": True,
            "schema_removed": schema_removed,
            "existing_volume_deleted": False,
            "data_classification": "simulated",
        }

    def monitor(self, *, allow_self_signed: bool, manifest_path: Path | None) -> dict:
        self.preflight()
        ps_output = self.run("ps", "--format", "json").stdout.strip()
        try:
            services = json.loads(ps_output)
            if isinstance(services, dict):
                services = [services]
        except json.JSONDecodeError:
            services = [json.loads(line) for line in ps_output.splitlines() if line.strip()]
        service_status = {
            item.get("Service"): {
                "state": item.get("State"),
                "health": item.get("Health"),
            }
            for item in services
        }

        context = ssl._create_unverified_context() if allow_self_signed else ssl.create_default_context()
        readiness_url = self.env["PUBLIC_BASE_URL"].rstrip("/") + "/api/v1/health/ready"
        with urllib.request.urlopen(readiness_url, timeout=10, context=context) as response:
            readiness = json.loads(response.read().decode("utf-8"))
            response_headers = {key.lower(): value for key, value in response.headers.items()}
        required_security_headers = {
            "strict-transport-security",
            "x-content-type-options",
            "x-frame-options",
            "content-security-policy",
        }
        security_headers_present = sorted(required_security_headers & response_headers.keys())

        external_metrics_status = None
        try:
            urllib.request.urlopen(
                self.env["PUBLIC_BASE_URL"].rstrip("/") + "/api/v1/metrics",
                timeout=10,
                context=context,
            )
        except urllib.error.HTTPError as exc:
            external_metrics_status = exc.code

        metrics_process = self.run(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            (
                "import urllib.request;"
                "print(urllib.request.urlopen("
                "'http://localhost:8000/api/v1/metrics',timeout=5"
                ").read().decode())"
            ),
        )
        metric_lines = [
            line
            for line in metrics_process.stdout.splitlines()
            if line and not line.startswith("#")
        ]

        backup_status = {"checked": False}
        if manifest_path is not None:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            created_at = datetime.fromisoformat(manifest["created_at"])
            age_hours = (datetime.now(UTC) - created_at).total_seconds() / 3600
            backup_status = {
                "checked": True,
                "status": manifest.get("status"),
                "age_hours": round(age_hours, 3),
                "sha256_present": bool(manifest.get("sha256")),
                "fresh_within_24h": age_hours <= 24,
            }

        all_healthy = service_status and all(
            value["state"] == "running" and value["health"] in {"healthy", ""}
            for value in service_status.values()
        )
        passed = (
            all_healthy
            and readiness.get("status") == "ready"
            and bool(metric_lines)
            and set(security_headers_present) == required_security_headers
            and external_metrics_status == 404
            and (not backup_status["checked"] or backup_status["fresh_within_24h"])
        )
        return {
            "status": "passed" if passed else "failed",
            "collected_at": utc_now(),
            "release_version": self.env["RELEASE_VERSION"],
            "data_classification": "simulated",
            "services": service_status,
            "readiness": readiness,
            "metric_sample_count": len(metric_lines),
            "https_security": {
                "required_headers_present": security_headers_present,
                "external_metrics_status": external_metrics_status,
            },
            "backup": backup_status,
            "secrets_in_snapshot": False,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--project-name", default="renewable-operations-private")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--output", type=Path)

    backup = subparsers.add_parser("backup")
    backup.add_argument("--output-dir", type=Path, required=True)
    backup.add_argument("--output", type=Path)

    restore = subparsers.add_parser("restore-drill")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--output", type=Path)

    monitor = subparsers.add_parser("monitor")
    monitor.add_argument("--allow-self-signed", action="store_true")
    monitor.add_argument("--backup-manifest", type=Path)
    monitor.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    deployment = PrivateDeployment(args.compose_file, args.env_file, args.project_name)
    try:
        if args.command == "preflight":
            result = deployment.preflight()
        elif args.command == "backup":
            result = deployment.backup(args.output_dir)
        elif args.command == "restore-drill":
            result = deployment.restore_drill(args.backup, args.manifest)
        elif args.command == "monitor":
            result = deployment.monitor(
                allow_self_signed=args.allow_self_signed,
                manifest_path=args.backup_manifest,
            )
        else:
            raise OperationError(f"unsupported command: {args.command}")
        write_json(args.output, result)
        return 0 if result.get("status") in {"passed", "completed"} else 1
    except (OperationError, subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "executed_at": utc_now(),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
