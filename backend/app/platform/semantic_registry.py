import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.platform_data import DatasetVersion, PlatformDataset, SemanticActivation
from app.models.semantic import (
    DataPolicy,
    SemanticDimension,
    SemanticField,
    SemanticFilter,
    SemanticMetric,
    SemanticModel,
    SemanticModelVersion,
    SemanticRelationship,
    SemanticTable,
    SemanticTimeDimension,
)
from app.platform.dataset_release import (
    ActiveDatasetResolver,
    DatasetReleaseError,
)
from app.platform.identity import IdentityContext
from app.platform.versioning import version_satisfies


class SemanticRegistryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checksum(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class SemanticModelRegistry:
    def __init__(self, db: Session):
        self.db = db

    def register_model(
        self,
        identity: IdentityContext,
        *,
        scenario_id: str,
        code: str,
        name: str,
        owner_subject_id: str,
    ) -> SemanticModel:
        existing = self.db.scalar(select(SemanticModel).where(
            SemanticModel.tenant_id == identity.tenant_id,
            SemanticModel.workspace_id == identity.workspace_id,
            SemanticModel.scenario_id == scenario_id,
            SemanticModel.code == code,
        ))
        if existing:
            return existing
        model = SemanticModel(
            semantic_model_id=f"SM-{uuid4()}",
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            scenario_id=scenario_id,
            code=code,
            name=name,
            owner_subject_id=owner_subject_id,
            status="ENABLED",
        )
        self.db.add(model)
        self.db.commit()
        return model

    def register_version(
        self,
        identity: IdentityContext,
        *,
        semantic_model_id: str,
        version: str,
        scenario_version: str,
        contract_version: str,
        dataset_compatibility: dict,
        definition: dict,
    ) -> SemanticModelVersion:
        model = self._scoped_model(identity, semantic_model_id)
        digest = _checksum(definition)
        existing = self.db.scalar(select(SemanticModelVersion).where(
            SemanticModelVersion.semantic_model_id == semantic_model_id,
            SemanticModelVersion.checksum == digest,
        ))
        if existing:
            return existing
        release = SemanticModelVersion(
            semantic_model_version_id=f"SMV-{uuid4()}",
            semantic_model_id=semantic_model_id,
            version=version,
            scenario_version=scenario_version,
            contract_version=contract_version,
            dataset_compatibility_json=_canonical(dataset_compatibility),
            model_json=_canonical(definition),
            checksum=digest,
            status="DRAFT",
            created_by=identity.subject_id,
        )
        self.db.add(release)
        self.db.flush()
        self._store_definition(identity, release, definition)
        self.db.commit()
        return release

    def publish(
        self,
        identity: IdentityContext,
        semantic_model_version_id: str,
        *,
        reviewer_subject_id: str,
    ) -> SemanticModelVersion:
        release, _ = self._scoped_version(identity, semantic_model_version_id)
        if release.status == "PUBLISHED":
            return release
        if release.status != "DRAFT":
            raise SemanticRegistryError("INVALID_STATE", "只有 DRAFT 语义版本可以发布")
        if not list(MetricRegistry(self.db).list_for_version(semantic_model_version_id)):
            raise SemanticRegistryError("EMPTY_MODEL", "语义版本至少需要一个指标")
        release.status = "PUBLISHED"
        release.reviewed_by = reviewer_subject_id
        release.published_at = datetime.now(UTC)
        self.db.commit()
        return release

    def assert_content_mutable(self, release: SemanticModelVersion) -> None:
        if release.status in {"PUBLISHED", "ACTIVE", "SUPERSEDED", "RETIRED"}:
            raise SemanticRegistryError(
                "IMMUTABLE_VERSION",
                "已发布或已激活的语义模型版本内容不可修改",
            )

    def _store_definition(
        self,
        identity: IdentityContext,
        release: SemanticModelVersion,
        definition: dict,
    ) -> None:
        table_ids: dict[str, str] = {}
        for item in definition.get("tables", []):
            record = SemanticTable(
                semantic_table_id=f"ST-{uuid4()}",
                semantic_model_version_id=release.semantic_model_version_id,
                code=item["code"],
                name=item["name"],
                physical_binding=item["physical_binding"],
                grain_json=_canonical(item.get("grain", [])),
                lineage_json=_canonical(item.get("lineage", {})),
            )
            table_ids[item["code"]] = record.semantic_table_id
            self.db.add(record)
        self.db.flush()
        for item in definition.get("fields", []):
            self.db.add(SemanticField(
                semantic_field_id=f"SF-{uuid4()}",
                semantic_table_id=table_ids[item["table"]],
                code=item["code"],
                name=item["name"],
                data_type=item["data_type"],
                physical_field=item["physical_field"],
                nullable=1 if item.get("nullable", True) else 0,
                classification=item.get("classification", "internal"),
                permission_policy_json=_canonical(item.get("permission_policy", {})),
                lineage_json=_canonical(item.get("lineage", {})),
            ))
        for item in definition.get("metrics", []):
            required = {
                "code", "name", "expression", "aggregation", "grain", "unit",
                "format", "owner", "version", "status",
            }
            if required - item.keys():
                raise SemanticRegistryError("INVALID_METRIC", "指标缺少合同必填字段")
            self.db.add(SemanticMetric(
                metric_id=f"MET-{uuid4()}",
                semantic_model_version_id=release.semantic_model_version_id,
                code=item["code"],
                name=item["name"],
                aliases_json=_canonical(item.get("aliases", [])),
                expression=item["expression"],
                aggregation=item["aggregation"],
                grain_json=_canonical(item["grain"]),
                time_field=item.get("time_field"),
                supported_dimensions_json=_canonical(item.get("supported_dimensions", [])),
                filters_json=_canonical(item.get("filters", [])),
                unit=item["unit"],
                format=item["format"],
                owner=item["owner"],
                version=item["version"],
                status=item["status"],
                permission_policy_json=_canonical(item.get("permission_policy", {})),
                lineage_json=_canonical(item.get("lineage", {})),
            ))
        for item in definition.get("dimensions", []):
            self.db.add(SemanticDimension(
                dimension_id=f"DIM-{uuid4()}",
                semantic_model_version_id=release.semantic_model_version_id,
                code=item["code"],
                name=item["name"],
                aliases_json=_canonical(item.get("aliases", [])),
                field_ref=item["field_ref"],
                data_type=item["data_type"],
                hierarchy_json=_canonical(item.get("hierarchy", [])),
                permission_policy_json=_canonical(item.get("permission_policy", {})),
                lineage_json=_canonical(item.get("lineage", {})),
            ))
        for item in definition.get("relationships", []):
            self.db.add(SemanticRelationship(
                relationship_id=f"R-{uuid4()}",
                semantic_model_version_id=release.semantic_model_version_id,
                code=item["code"],
                source_table=item["source_table"],
                source_fields_json=_canonical(item["source_fields"]),
                target_table=item["target_table"],
                target_fields_json=_canonical(item["target_fields"]),
                cardinality=item["cardinality"],
                join_type=item.get("join_type", "inner"),
                status=item.get("status", "PUBLISHED"),
            ))
        for item in definition.get("time_dimensions", []):
            self.db.add(SemanticTimeDimension(
                time_dimension_id=f"TD-{uuid4()}",
                semantic_model_version_id=release.semantic_model_version_id,
                code=item["code"],
                field_ref=item["field_ref"],
                timezone=item.get("timezone", "UTC"),
                grains_json=_canonical(item["grains"]),
                fiscal_calendar_json=_canonical(item.get("fiscal_calendar", {})),
            ))
        for item in definition.get("filters", []):
            self.db.add(SemanticFilter(
                semantic_filter_id=f"FLT-{uuid4()}",
                semantic_model_version_id=release.semantic_model_version_id,
                code=item["code"],
                expression_json=_canonical(item["expression"]),
                required=1 if item.get("required", False) else 0,
                permission_policy_json=_canonical(item.get("permission_policy", {})),
            ))
        for item in definition.get("policies", []):
            self.db.add(DataPolicy(
                data_policy_id=f"POL-{uuid4()}",
                tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id,
                semantic_model_version_id=release.semantic_model_version_id,
                code=item["code"],
                roles_json=_canonical(item.get("roles", [])),
                row_filter_json=_canonical(item.get("row_filter", {})),
                column_masks_json=_canonical(item.get("column_masks", {})),
                export_allowed=1 if item.get("export_allowed", False) else 0,
                status=item.get("status", "PUBLISHED"),
            ))

    def _scoped_model(
        self, identity: IdentityContext, semantic_model_id: str
    ) -> SemanticModel:
        model = self.db.get(SemanticModel, semantic_model_id)
        if (
            model is None
            or model.tenant_id != identity.tenant_id
            or model.workspace_id != identity.workspace_id
        ):
            raise SemanticRegistryError("MODEL_NOT_FOUND", "语义模型不存在或不在当前工作区")
        return model

    def _scoped_version(
        self, identity: IdentityContext, semantic_model_version_id: str
    ) -> tuple[SemanticModelVersion, SemanticModel]:
        release = self.db.get(SemanticModelVersion, semantic_model_version_id)
        if release is None:
            raise SemanticRegistryError("VERSION_NOT_FOUND", "语义模型版本不存在")
        return release, self._scoped_model(identity, release.semantic_model_id)


class MetricRegistry:
    def __init__(self, db: Session):
        self.db = db

    def list_for_version(self, version_id: str) -> tuple[SemanticMetric, ...]:
        return tuple(self.db.scalars(select(SemanticMetric).where(
            SemanticMetric.semantic_model_version_id == version_id
        ).order_by(SemanticMetric.code)).all())

    def get(self, version_id: str, code: str) -> SemanticMetric:
        item = self.db.scalar(select(SemanticMetric).where(
            SemanticMetric.semantic_model_version_id == version_id,
            SemanticMetric.code == code,
            SemanticMetric.status == "PUBLISHED",
        ))
        if item is None:
            raise SemanticRegistryError("METRIC_NOT_FOUND", "指标未在当前语义版本发布")
        return item


class DimensionRegistry:
    def __init__(self, db: Session):
        self.db = db

    def list_for_version(self, version_id: str) -> tuple[SemanticDimension, ...]:
        return tuple(self.db.scalars(select(SemanticDimension).where(
            SemanticDimension.semantic_model_version_id == version_id
        ).order_by(SemanticDimension.code)).all())


class RelationshipRegistry:
    def __init__(self, db: Session):
        self.db = db

    def list_for_version(self, version_id: str) -> tuple[SemanticRelationship, ...]:
        return tuple(self.db.scalars(select(SemanticRelationship).where(
            SemanticRelationship.semantic_model_version_id == version_id,
            SemanticRelationship.status == "PUBLISHED",
        ).order_by(SemanticRelationship.code)).all())


@dataclass(frozen=True)
class ActiveSemanticContext:
    tenant_id: str
    workspace_id: str
    scenario_id: str
    scenario_version: str
    semantic_model_version_id: str
    semantic_version: str
    dataset_id: str
    dataset_version_id: str
    dataset_version: int
    dataset_checksum: str
    dataset_period_start: str | None
    dataset_period_end_exclusive: str | None
    data_classification: str
    source_binding: dict


class ActiveSemanticResolver:
    def __init__(self, db: Session):
        self.db = db

    def resolve(
        self,
        identity: IdentityContext,
        *,
        scenario_id: str,
        dataset_code: str,
    ) -> ActiveSemanticContext:
        try:
            dataset, dataset_version, pointer = ActiveDatasetResolver(self.db).resolve(
                identity, scenario_id=scenario_id, dataset_code=dataset_code
            )
        except DatasetReleaseError as exc:
            raise SemanticRegistryError(exc.code, exc.message) from exc
        if not pointer.active_semantic_model_version_id:
            raise SemanticRegistryError("NO_ACTIVE_SEMANTIC_VERSION", "当前数据集未绑定 ACTIVE 语义版本")
        semantic_version = self.db.get(
            SemanticModelVersion, pointer.active_semantic_model_version_id
        )
        if semantic_version is None or semantic_version.status != "ACTIVE":
            raise SemanticRegistryError("STALE_SEMANTIC_ACTIVATION", "ACTIVE 语义指针状态不一致")
        model = self.db.get(SemanticModel, semantic_version.semantic_model_id)
        if (
            model is None
            or model.tenant_id != identity.tenant_id
            or model.workspace_id != identity.workspace_id
            or model.scenario_id != scenario_id
        ):
            raise SemanticRegistryError("MODEL_SCOPE_MISMATCH", "语义模型身份范围不匹配")
        compatibility = json.loads(semantic_version.dataset_compatibility_json)
        expected = compatibility.get(dataset.code, {})
        if expected.get("checksum") and expected["checksum"] != dataset_version.checksum:
            raise SemanticRegistryError("INCOMPATIBLE_DATASET_VERSION", "语义版本与 ACTIVE 数据集校验和不兼容")
        if not version_satisfies(semantic_version.version, dataset_version.compatible_semantic_range):
            raise SemanticRegistryError("INCOMPATIBLE_SEMANTIC_VERSION", "数据集不接受当前语义版本")
        return ActiveSemanticContext(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            scenario_id=scenario_id,
            scenario_version=pointer.scenario_version,
            semantic_model_version_id=semantic_version.semantic_model_version_id,
            semantic_version=semantic_version.version,
            dataset_id=dataset.dataset_id,
            dataset_version_id=dataset_version.dataset_version_id,
            dataset_version=dataset_version.version,
            dataset_checksum=dataset_version.checksum,
            dataset_period_start=dataset_version.period_start,
            dataset_period_end_exclusive=dataset_version.period_end_exclusive,
            data_classification=dataset.data_classification,
            source_binding=json.loads(dataset_version.source_binding_json),
        )
