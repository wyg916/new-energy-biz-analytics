from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.governance.audit import record_governance_event
from app.governance.authorization import AuthorizationService, request_context
from app.governance.contracts import CredentialStatus
from app.governance.models import CredentialReference
from app.governance.secrets import CredentialReferenceService, SecretResolutionError
from app.models.integration import DataSourceConnection
from app.platform.identity import IdentityContext
from app.preproduction.models import PreproductionDataSourceGovernance


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SENSITIVE_COLUMN = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|credential|cookie|private[_-]?key|id[_-]?card|phone|email)"
)
LIFECYCLE_STATES = {
    "DRAFT", "REVIEW", "APPROVED", "PUBLISHED", "ACTIVE", "SUPERSEDED",
    "DISABLED", "ROLLED_BACK", "ARCHIVED",
}


class DataSourceGovernanceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DataSourceGovernanceService:
    """Tenant-scoped, approval-gated data-source lifecycle for simulated P4 data."""

    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity
        self.settings = get_settings()

    def list(self) -> list[dict]:
        self._authorize("datasource.view", "*")
        rows = self.db.execute(select(DataSourceConnection, PreproductionDataSourceGovernance).join(
            PreproductionDataSourceGovernance,
            PreproductionDataSourceGovernance.source_id == DataSourceConnection.source_id,
        ).where(
            PreproductionDataSourceGovernance.tenant_id == self.identity.tenant_id,
            PreproductionDataSourceGovernance.workspace_id == self.identity.workspace_id,
        ).order_by(DataSourceConnection.display_name, desc(PreproductionDataSourceGovernance.version))).all()
        return [self.payload(source, governance) for source, governance in rows]

    def create(
        self,
        *,
        display_name: str,
        source_type: str,
        host: str | None,
        port: int | None,
        database_name: str | None,
        username: str | None,
        credential_ref_id: str | None,
        scenario_id: str,
        connection_options: dict | None = None,
    ) -> DataSourceConnection:
        self._authorize("datasource.manage", display_name, scenario_id=scenario_id)
        if source_type != "postgresql":
            raise DataSourceGovernanceError("P4_SOURCE_TYPE_NOT_ALLOWED", "P4 预生产仅开放受控只读 PostgreSQL 数据源")
        if scenario_id not in {"charging_ops", "sales_ops"}:
            raise DataSourceGovernanceError("SCENARIO_NOT_ALLOWED", "数据源必须绑定已批准场景")
        if not host or not database_name or not username:
            raise DataSourceGovernanceError("SOURCE_CONFIGURATION_INCOMPLETE", "数据库主机、库名和用户名不能为空")
        credential = self._credential(credential_ref_id, action="datasource.connect")
        max_version = int(self.db.scalar(select(func.max(PreproductionDataSourceGovernance.version)).join(
            DataSourceConnection,
            DataSourceConnection.source_id == PreproductionDataSourceGovernance.source_id,
        ).where(
            PreproductionDataSourceGovernance.tenant_id == self.identity.tenant_id,
            PreproductionDataSourceGovernance.workspace_id == self.identity.workspace_id,
            DataSourceConnection.display_name == display_name,
        )) or 0)
        record = DataSourceConnection(
            source_id=f"DS-P4-{uuid4()}",
            display_name=display_name,
            source_type=source_type,
            host=host,
            port=port or 5432,
            database_name=database_name,
            username=username,
            credential_env_key=None,
            status="configured",
            connection_options_json=json.dumps(connection_options or {}, ensure_ascii=False, sort_keys=True),
        )
        self.db.add(record)
        self.db.flush()
        governance = PreproductionDataSourceGovernance(
            governance_id=f"DSGOV-P4-{uuid4()}", source_id=record.source_id,
            credential_ref_id=credential.credential_ref_id,
            tenant_id=self.identity.tenant_id, workspace_id=self.identity.workspace_id,
            scenario_id=scenario_id, data_classification="simulated",
            lifecycle_status="DRAFT", version=max_version + 1,
        )
        self.db.add(governance)
        self.db.flush()
        self._audit(record, "datasource.created", "SUCCESS", {"version": governance.version})
        self.db.commit()
        return record

    def test_connection(self, source_id: str) -> dict:
        source = self._owned(source_id)
        governance = self._governance(source)
        self._authorize("datasource.manage", source_id, scenario_id=governance.scenario_id)
        started = time.perf_counter()
        secret = self._resolve(source, "datasource.connect")
        try:
            with psycopg.connect(
                host=source.host,
                port=source.port or 5432,
                dbname=source.database_name,
                user=source.username,
                password=secret,
                connect_timeout=5,
                options="-c default_transaction_read_only=on -c statement_timeout=5000",
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW transaction_read_only")
                    read_only = cursor.fetchone()[0]
                    cursor.execute("SELECT current_database(), current_user")
                    database, current_user = cursor.fetchone()
        except (psycopg.Error, OSError) as exc:
            source.status = "unavailable"
            source.last_error_code = "DATASOURCE_CONNECTION_FAILED"
            source.last_tested_at = datetime.now(UTC)
            self._audit(source, "datasource.connection_test", "FAILED", {"error_code": source.last_error_code})
            self.db.commit()
            raise DataSourceGovernanceError("DATASOURCE_CONNECTION_FAILED", "数据源连通性测试失败") from exc
        latency = round((time.perf_counter() - started) * 1000)
        source.status = "connected"
        source.last_error_code = None
        source.last_latency_ms = latency
        source.last_tested_at = datetime.now(UTC)
        options = self._options(source)
        options["connection_test"] = {
            "status": "PASS", "read_only": read_only == "on",
            "database_hash": self._digest(str(database)),
            "principal_hash": self._digest(str(current_user)),
            "tested_at": source.last_tested_at.isoformat(),
        }
        source.connection_options_json = json.dumps(options, sort_keys=True)
        self._audit(source, "datasource.connection_test", "SUCCESS", {"read_only": read_only == "on", "latency_ms": latency})
        self.db.commit()
        return {"source_id": source.source_id, "status": "PASS", "read_only": read_only == "on", "latency_ms": latency}

    def discover_schema(self, source_id: str) -> dict:
        source = self._owned(source_id)
        governance = self._governance(source)
        self._authorize("datasource.manage", source_id, scenario_id=governance.scenario_id)
        secret = self._resolve(source, "datasource.discover")
        try:
            with psycopg.connect(
                host=source.host, port=source.port or 5432, dbname=source.database_name,
                user=source.username, password=secret, connect_timeout=5,
                options="-c default_transaction_read_only=on -c statement_timeout=5000",
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """SELECT table_schema, table_name, column_name, data_type
                           FROM information_schema.columns
                           WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                           ORDER BY table_schema, table_name, ordinal_position LIMIT 500"""
                    )
                    rows = cursor.fetchall()
        except (psycopg.Error, OSError) as exc:
            raise DataSourceGovernanceError("SCHEMA_DISCOVERY_FAILED", "Schema 发现失败") from exc
        relations: dict[str, list[dict]] = {}
        filtered = 0
        for schema, table, column, data_type in rows:
            key = f"{schema}.{table}"
            if SENSITIVE_COLUMN.search(str(column)):
                filtered += 1
                continue
            relations.setdefault(key, []).append({"name": column, "type": data_type})
        options = self._options(source)
        options["schema_discovery"] = {
            "status": "PASS", "relation_count": len(relations), "column_count": sum(map(len, relations.values())),
            "sensitive_columns_filtered": filtered, "schema_hash": self._digest(json.dumps(relations, sort_keys=True)),
            "discovered_at": datetime.now(UTC).isoformat(),
        }
        source.connection_options_json = json.dumps(options, sort_keys=True)
        self._audit(source, "datasource.schema_discovered", "SUCCESS", options["schema_discovery"])
        self.db.commit()
        return {"source_id": source.source_id, "relations": relations, **options["schema_discovery"]}

    def profile(self, source_id: str, *, relation: str) -> dict:
        source = self._owned(source_id)
        governance = self._governance(source)
        self._authorize("datasource.manage", source_id, scenario_id=governance.scenario_id)
        parts = relation.split(".")
        if len(parts) != 2 or not all(IDENTIFIER.fullmatch(part) for part in parts):
            raise DataSourceGovernanceError("RELATION_NOT_ALLOWED", "画像关系必须是发现后的 schema.table")
        secret = self._resolve(source, "datasource.profile")
        quoted = ".".join(f'"{part}"' for part in parts)
        try:
            with psycopg.connect(
                host=source.host, port=source.port or 5432, dbname=source.database_name,
                user=source.username, password=secret, connect_timeout=5,
                options="-c default_transaction_read_only=on -c statement_timeout=5000",
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """SELECT column_name FROM information_schema.columns
                           WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position LIMIT 50""",
                        (parts[0], parts[1]),
                    )
                    allowed_columns = [row[0] for row in cursor.fetchall() if IDENTIFIER.fullmatch(row[0]) and not SENSITIVE_COLUMN.search(row[0])]
                    cursor.execute(f"SELECT count(*) FROM {quoted}")
                    row_count = int(cursor.fetchone()[0])
        except (psycopg.Error, OSError) as exc:
            raise DataSourceGovernanceError("DATASOURCE_PROFILE_FAILED", "数据画像失败") from exc
        profile = {
            "status": "PASS", "relation": relation, "row_count": row_count,
            "allowed_column_count": len(allowed_columns),
            "sensitive_columns_filtered": True,
            "profile_hash": self._digest(json.dumps({"relation": relation, "rows": row_count, "columns": allowed_columns}, sort_keys=True)),
            "profiled_at": datetime.now(UTC).isoformat(),
        }
        options = self._options(source)
        options["profile"] = profile
        options["approved_relations"] = [relation]
        options["allowed_columns"] = {relation: allowed_columns}
        source.connection_options_json = json.dumps(options, sort_keys=True)
        self._audit(source, "datasource.profiled", "SUCCESS", {key: value for key, value in profile.items() if key != "relation"})
        self.db.commit()
        return {"source_id": source.source_id, **profile}

    def submit(self, source_id: str) -> DataSourceConnection:
        source = self._owned(source_id)
        governance = self._governance(source)
        self._authorize("datasource.manage", source_id, scenario_id=governance.scenario_id)
        if governance.lifecycle_status != "DRAFT":
            raise DataSourceGovernanceError("DATASOURCE_INVALID_STATE", "仅 DRAFT 数据源可提交审核")
        options = self._options(source)
        if options.get("connection_test", {}).get("status") != "PASS" or options.get("schema_discovery", {}).get("status") != "PASS" or options.get("profile", {}).get("status") != "PASS":
            raise DataSourceGovernanceError("DATASOURCE_EVIDENCE_INCOMPLETE", "连通性、Schema 发现和数据画像证据必须全部通过")
        governance.lifecycle_status = "REVIEW"
        governance.updated_at = datetime.now(UTC)
        self._audit(source, "datasource.submitted", "SUCCESS")
        self.db.commit()
        return source

    def approve(self, source_id: str) -> DataSourceConnection:
        source = self._transition(source_id, "REVIEW", "APPROVED", "datasource.review")
        governance = self._governance(source)
        governance.approved_by = self.identity.subject_id
        governance.approved_at = datetime.now(UTC)
        self._audit(source, "datasource.approved", "SUCCESS")
        self.db.commit()
        return source

    def publish(self, source_id: str) -> DataSourceConnection:
        source = self._transition(source_id, "APPROVED", "PUBLISHED", "datasource.activate")
        self._audit(source, "datasource.published", "SUCCESS")
        self.db.commit()
        return source

    def activate(self, source_id: str) -> DataSourceConnection:
        source = self._transition(source_id, "PUBLISHED", "ACTIVE", "datasource.activate")
        governance = self._governance(source)
        self._credential(governance.credential_ref_id, action="datasource.connect")
        active_rows = self.db.execute(select(DataSourceConnection, PreproductionDataSourceGovernance).join(
            PreproductionDataSourceGovernance,
            PreproductionDataSourceGovernance.source_id == DataSourceConnection.source_id,
        ).where(
            PreproductionDataSourceGovernance.tenant_id == governance.tenant_id,
            PreproductionDataSourceGovernance.workspace_id == governance.workspace_id,
            DataSourceConnection.display_name == source.display_name,
            PreproductionDataSourceGovernance.lifecycle_status == "ACTIVE",
            DataSourceConnection.source_id != source.source_id,
        )).all()
        for _current, current_governance in active_rows:
            current_governance.lifecycle_status = "SUPERSEDED"
        governance.activated_by = self.identity.subject_id
        governance.activated_at = datetime.now(UTC)
        self._audit(source, "datasource.activated", "SUCCESS")
        self.db.commit()
        return source

    def disable(self, source_id: str) -> DataSourceConnection:
        source = self._owned(source_id)
        governance = self._governance(source)
        self._authorize("datasource.manage", source_id, scenario_id=governance.scenario_id)
        if governance.lifecycle_status not in {"ACTIVE", "PUBLISHED", "APPROVED"}:
            raise DataSourceGovernanceError("DATASOURCE_INVALID_STATE", "当前状态不能停用")
        governance.lifecycle_status = "DISABLED"
        governance.disabled_at = datetime.now(UTC)
        self._audit(source, "datasource.disabled", "SUCCESS")
        self.db.commit()
        return source

    def archive(self, source_id: str) -> DataSourceConnection:
        source = self._owned(source_id)
        governance = self._governance(source)
        self._authorize("datasource.manage", source_id, scenario_id=governance.scenario_id)
        if governance.lifecycle_status not in {"DRAFT", "DISABLED", "ROLLED_BACK", "SUPERSEDED"}:
            raise DataSourceGovernanceError("DATASOURCE_INVALID_STATE", "仅非活动数据源可以归档")
        governance.lifecycle_status = "ARCHIVED"
        self._audit(source, "datasource.archived", "SUCCESS")
        self.db.commit()
        return source

    def rotate(self, source_id: str, *, secret_identifier: str) -> DataSourceConnection:
        source = self._owned(source_id)
        governance = self._governance(source)
        self._authorize("datasource.manage", source_id, scenario_id=governance.scenario_id)
        if not governance.credential_ref_id:
            raise DataSourceGovernanceError("CREDENTIAL_REFERENCE_REQUIRED", "数据源没有可轮换凭据引用")
        replacement = CredentialReferenceService(self.db, self.identity).rotate(
            governance.credential_ref_id, secret_identifier=secret_identifier,
        )
        clone = DataSourceConnection(
            source_id=f"DS-P4-{uuid4()}", display_name=source.display_name, source_type=source.source_type,
            host=source.host, port=source.port, database_name=source.database_name, username=source.username,
            credential_env_key=None,
            connection_options_json="{}", status="configured",
        )
        self.db.add(clone)
        self.db.flush()
        clone_governance = PreproductionDataSourceGovernance(
            governance_id=f"DSGOV-P4-{uuid4()}", source_id=clone.source_id,
            credential_ref_id=replacement.credential_ref_id,
            tenant_id=governance.tenant_id, workspace_id=governance.workspace_id,
            scenario_id=governance.scenario_id, data_classification=governance.data_classification,
            lifecycle_status="DRAFT", version=governance.version + 1,
        )
        self.db.add(clone_governance)
        self.db.flush()
        self._audit(clone, "datasource.rotated", "SUCCESS", {"previous_source_id": source.source_id, "version": clone_governance.version})
        self.db.commit()
        return clone

    def rollback(self, source_id: str, *, target_source_id: str) -> DataSourceConnection:
        current = self._owned(source_id)
        target = self._owned(target_source_id)
        current_governance = self._governance(current)
        target_governance = self._governance(target)
        self._authorize("datasource.rollback", source_id, scenario_id=current_governance.scenario_id)
        if current_governance.lifecycle_status != "ACTIVE" or current.display_name != target.display_name:
            raise DataSourceGovernanceError("ROLLBACK_TARGET_MISMATCH", "回滚源和目标不匹配")
        if target_governance.lifecycle_status not in {"SUPERSEDED", "DISABLED", "ROLLED_BACK"} or not target_governance.approved_by:
            raise DataSourceGovernanceError("ROLLBACK_TARGET_NOT_APPROVED", "回滚目标不是已批准历史版本")
        self._credential(target_governance.credential_ref_id, action="datasource.connect")
        current_governance.lifecycle_status = "ROLLED_BACK"
        clone = DataSourceConnection(
            source_id=f"DS-P4-{uuid4()}", display_name=target.display_name, source_type=target.source_type,
            host=target.host, port=target.port, database_name=target.database_name, username=target.username,
            credential_env_key=None, connection_options_json=target.connection_options_json, status="connected",
        )
        self.db.add(clone)
        self.db.flush()
        self.db.add(PreproductionDataSourceGovernance(
            governance_id=f"DSGOV-P4-{uuid4()}", source_id=clone.source_id,
            credential_ref_id=target_governance.credential_ref_id,
            tenant_id=target_governance.tenant_id, workspace_id=target_governance.workspace_id,
            scenario_id=target_governance.scenario_id, data_classification=target_governance.data_classification,
            lifecycle_status="ACTIVE", version=current_governance.version + 1,
            approved_by=target_governance.approved_by, approved_at=target_governance.approved_at,
            activated_by=self.identity.subject_id, activated_at=datetime.now(UTC),
        ))
        self.db.flush()
        self._audit(clone, "datasource.rolled_back", "SUCCESS", {"rollback_of": current.source_id, "target_source_id": target.source_id})
        self.db.commit()
        return clone

    def _transition(self, source_id: str, expected: str, target: str, permission: str) -> DataSourceConnection:
        if target not in LIFECYCLE_STATES:
            raise AssertionError(target)
        source = self._owned(source_id)
        governance = self._governance(source)
        self._authorize(permission, source_id, scenario_id=governance.scenario_id)
        if governance.lifecycle_status != expected:
            raise DataSourceGovernanceError("DATASOURCE_INVALID_STATE", f"仅 {expected} 数据源可转为 {target}")
        governance.lifecycle_status = target
        governance.updated_at = datetime.now(UTC)
        return source

    def _owned(self, source_id: str) -> DataSourceConnection:
        source = self.db.get(DataSourceConnection, source_id)
        governance = self.db.scalar(select(PreproductionDataSourceGovernance).where(
            PreproductionDataSourceGovernance.source_id == source_id,
            PreproductionDataSourceGovernance.tenant_id == self.identity.tenant_id,
            PreproductionDataSourceGovernance.workspace_id == self.identity.workspace_id,
        ))
        if source is None or governance is None:
            raise DataSourceGovernanceError("DATASOURCE_NOT_FOUND", "数据源不存在")
        return source

    def _governance(self, source: DataSourceConnection) -> PreproductionDataSourceGovernance:
        governance = self.db.scalar(select(PreproductionDataSourceGovernance).where(
            PreproductionDataSourceGovernance.source_id == source.source_id,
        ))
        if governance is None:
            raise DataSourceGovernanceError("DATASOURCE_NOT_FOUND", "数据源治理记录不存在")
        return governance

    def _credential(self, credential_ref_id: str | None, *, action: str) -> CredentialReference:
        if not credential_ref_id:
            raise DataSourceGovernanceError("CREDENTIAL_REFERENCE_REQUIRED", "预生产数据源必须使用 CredentialReference")
        credential = self.db.get(CredentialReference, credential_ref_id)
        if credential is None or credential.tenant_id != self.identity.tenant_id or credential.workspace_id != self.identity.workspace_id:
            raise DataSourceGovernanceError("CREDENTIAL_REFERENCE_NOT_FOUND", "凭据引用不存在")
        if credential.status != CredentialStatus.ACTIVE:
            raise DataSourceGovernanceError("CREDENTIAL_REFERENCE_NOT_ACTIVE", "凭据引用未激活")
        allowed = set(json.loads(credential.allowed_actions_json))
        if "*" not in allowed and action not in allowed:
            raise DataSourceGovernanceError("CREDENTIAL_ACTION_NOT_ALLOWED", "凭据引用未授权该操作")
        return credential

    def _resolve(self, source: DataSourceConnection, action: str) -> str:
        governance = self._governance(source)
        try:
            return CredentialReferenceService(self.db, self.identity).resolve(
                governance.credential_ref_id, action=action, trace_id=self.identity.request_id,
            ).value
        except SecretResolutionError as exc:
            raise DataSourceGovernanceError(exc.code, "数据源凭据解析失败") from exc

    def _authorize(self, action: str, resource_id: str, *, scenario_id: str | None = None) -> None:
        AuthorizationService(self.db, self.identity).require(request_context(
            self.identity, action=action, resource_type="datasource", resource_id=resource_id,
            scenario_id=scenario_id, data_classification="simulated", environment=self.settings.app_env,
            trace_id=self.identity.request_id,
        ))

    def _audit(self, source: DataSourceConnection, action: str, result: str, detail: dict | None = None) -> None:
        governance = self._governance(source)
        record_governance_event(
            self.db, self.identity, action=action, resource_type="datasource",
            resource_id=source.source_id, result=result,
            detail={"lifecycle_status": governance.lifecycle_status, "version": governance.version, **(detail or {})},
        )

    @staticmethod
    def _options(source: DataSourceConnection) -> dict:
        try:
            value = json.loads(source.connection_options_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def payload(
        self,
        source: DataSourceConnection,
        governance: PreproductionDataSourceGovernance | None = None,
    ) -> dict:
        governance = governance or self._governance(source)
        options = DataSourceGovernanceService._options(source)
        return {
            "source_id": source.source_id, "display_name": source.display_name,
            "source_type": source.source_type, "tenant_id": governance.tenant_id,
            "workspace_id": governance.workspace_id, "scenario_id": governance.scenario_id,
            "data_classification": governance.data_classification,
            "lifecycle_status": governance.lifecycle_status, "version": governance.version,
            "credential_ref_id": governance.credential_ref_id,
            "credential_value_returned": False,
            "connection_test_status": options.get("connection_test", {}).get("status", "NOT_RUN"),
            "schema_discovery_status": options.get("schema_discovery", {}).get("status", "NOT_RUN"),
            "profile_status": options.get("profile", {}).get("status", "NOT_RUN"),
            "last_tested_at": source.last_tested_at.isoformat() if source.last_tested_at else None,
            "approved_by": governance.approved_by, "activated_by": governance.activated_by,
        }
