from datetime import UTC, datetime

import pytest

from app.core.database import SessionLocal
from app.models.semantic import SemanticModelVersion
from app.platform.dataset_release import (
    DatasetReleaseError,
    DatasetVersionService,
    ReleaseService,
    SemanticActivationService,
)
from app.platform.identity import IdentityContext
from app.platform.semantic_registry import (
    ActiveSemanticResolver,
    DimensionRegistry,
    MetricRegistry,
    RelationshipRegistry,
    SemanticModelRegistry,
    SemanticRegistryError,
)


def identity(subject: str = "owner", tenant: str = "tenant-a") -> IdentityContext:
    return IdentityContext(
        subject_id=subject,
        tenant_id=tenant,
        org_id="org-a",
        workspace_id="workspace-a",
        roles=("semantic_owner",),
        groups=(),
        data_scopes=("all",),
        auth_strength="test",
        issued_at=datetime.now(UTC),
        request_id=f"request-{subject}",
    )


def definition() -> dict:
    return {
        "tables": [
            {
                "code": "fact",
                "name": "Fact",
                "physical_binding": "semantic.fact_view",
                "grain": ["entity_id", "event_time"],
                "lineage": {"source": "active_dataset"},
            },
            {
                "code": "entity",
                "name": "Entity",
                "physical_binding": "semantic.entity_view",
                "grain": ["entity_id"],
                "lineage": {"source": "active_dataset"},
            },
        ],
        "fields": [
            {
                "table": "fact",
                "code": "amount",
                "name": "Amount",
                "data_type": "number",
                "physical_field": "amount",
                "nullable": False,
            },
            {
                "table": "fact",
                "code": "event_time",
                "name": "Event time",
                "data_type": "datetime",
                "physical_field": "event_time",
                "nullable": False,
            },
        ],
        "metrics": [
            {
                "code": "total_amount",
                "name": "Total amount",
                "aliases": ["amount total"],
                "expression": "SUM(fact.amount)",
                "aggregation": "sum",
                "grain": ["workspace"],
                "time_field": "fact.event_time",
                "supported_dimensions": ["entity"],
                "filters": [],
                "unit": "currency",
                "format": "0.00",
                "owner": "metric-owner",
                "version": "1.0.0",
                "status": "PUBLISHED",
                "permission_policy": {"roles": ["reader"]},
                "lineage": {"fields": ["fact.amount"]},
            },
        ],
        "dimensions": [
            {
                "code": "entity",
                "name": "Entity",
                "aliases": [],
                "field_ref": "fact.entity_id",
                "data_type": "string",
                "hierarchy": [],
                "permission_policy": {},
                "lineage": {"fields": ["fact.entity_id"]},
            },
        ],
        "relationships": [
            {
                "code": "fact_to_entity",
                "source_table": "fact",
                "source_fields": ["entity_id"],
                "target_table": "entity",
                "target_fields": ["entity_id"],
                "cardinality": "many_to_one",
            },
        ],
        "time_dimensions": [
            {
                "code": "event_time",
                "field_ref": "fact.event_time",
                "timezone": "UTC",
                "grains": ["day", "month"],
            },
        ],
        "filters": [
            {
                "code": "workspace_scope",
                "expression": {"field": "workspace_id", "source": "identity"},
                "required": True,
            },
        ],
        "policies": [
            {
                "code": "reader",
                "roles": ["reader"],
                "row_filter": {"scope": "workspace"},
                "column_masks": {},
                "export_allowed": False,
            },
        ],
    }


def dataset_version(db, ctx: IdentityContext, key: str = "v1"):
    dataset_service = DatasetVersionService(db)
    dataset = dataset_service.create_dataset(
        ctx,
        code="operations",
        name="Operations",
        scenario_id="scenario-a",
        owner_subject_id=ctx.subject_id,
        data_classification="simulated",
    )
    version = dataset_service.create_version(
        ctx,
        dataset_id=dataset.dataset_id,
        mapping=[{"source": "source_id", "target": "entity_id"}],
        schema={"fields": [{"name": "entity_id", "type": "string"}]},
        source_binding={"relations": ["semantic.fact_view"]},
        source_version=f"source-{key}",
        quality_run_id=f"quality-{key}",
        quality_status="PASSED",
        quality_rules=[{"rule": "required", "status": "PASSED"}],
        row_count=3,
        period_start="2026-01-01",
        period_end_exclusive="2026-02-01",
        compatible_semantic_range=">=1.0.0,<2.0.0",
        idempotency_key=f"create-{key}",
    )
    release = ReleaseService(db)
    if version.status == "QUALITY_PASSED":
        release.submit(ctx, version.dataset_version_id)
        release.decide(ctx, version.dataset_version_id, approved=True)
        release.publish(ctx, version.dataset_version_id, idempotency_key=f"publish-{key}")
    return dataset, version


def semantic_version(
    db,
    ctx: IdentityContext,
    version: str = "1.0.0",
    publish: bool = True,
):
    registry = SemanticModelRegistry(db)
    model_definition = definition()
    model_definition["metadata"] = {"release_version": version}
    model = registry.register_model(
        ctx,
        scenario_id="scenario-a",
        code="operations-model",
        name="Operations model",
        owner_subject_id=ctx.subject_id,
    )
    release = registry.register_version(
        ctx,
        semantic_model_id=model.semantic_model_id,
        version=version,
        scenario_version="1.0.0",
        contract_version="0.1",
        dataset_compatibility={"operations": {}},
        definition=model_definition,
    )
    if publish:
        registry.publish(ctx, release.semantic_model_version_id, reviewer_subject_id="reviewer")
    return model, release


def test_registry_loads_generic_entities_and_published_version_is_immutable() -> None:
    with SessionLocal() as db:
        ctx = identity()
        _, release = semantic_version(db, ctx)
        assert len(MetricRegistry(db).list_for_version(release.semantic_model_version_id)) == 1
        assert len(DimensionRegistry(db).list_for_version(release.semantic_model_version_id)) == 1
        assert len(RelationshipRegistry(db).list_for_version(release.semantic_model_version_id)) == 1
        metric = MetricRegistry(db).get(release.semantic_model_version_id, "total_amount")
        assert metric.expression == "SUM(fact.amount)"
        with pytest.raises(SemanticRegistryError) as exc:
            SemanticModelRegistry(db).assert_content_mutable(release)
        assert exc.value.code == "IMMUTABLE_VERSION"


def test_active_resolver_requires_atomic_dataset_and_semantic_activation() -> None:
    with SessionLocal() as db:
        ctx = identity()
        dataset, data_release = dataset_version(db, ctx)
        _, semantic_release = semantic_version(db, ctx)
        SemanticActivationService(db).activate(
            ctx,
            dataset_version_id=data_release.dataset_version_id,
            scenario_version="1.0.0",
            semantic_model_version_id=semantic_release.semantic_model_version_id,
            idempotency_key="activate-all",
        )
        context = ActiveSemanticResolver(db).resolve(
            ctx, scenario_id="scenario-a", dataset_code="operations"
        )
        assert context.dataset_version_id == data_release.dataset_version_id
        assert context.semantic_version == "1.0.0"
        assert context.source_binding == {"relations": ["semantic.fact_view"]}
        assert db.get(
            SemanticModelVersion, semantic_release.semantic_model_version_id
        ).status == "ACTIVE"


def test_unpublished_or_incompatible_semantic_version_is_rejected() -> None:
    with SessionLocal() as db:
        ctx = identity()
        _, data_release = dataset_version(db, ctx)
        _, draft = semantic_version(db, ctx, publish=False)
        with pytest.raises(DatasetReleaseError) as exc:
            SemanticActivationService(db).activate(
                ctx,
                dataset_version_id=data_release.dataset_version_id,
                scenario_version="1.0.0",
                semantic_model_version_id=draft.semantic_model_version_id,
                idempotency_key="activate-draft",
            )
        assert exc.value.code == "SEMANTIC_VERSION_INVALID"

    with SessionLocal() as db:
        ctx = identity()
        _, data_release = dataset_version(db, ctx)
        _, incompatible = semantic_version(db, ctx, version="2.0.0")
        with pytest.raises(DatasetReleaseError) as exc:
            SemanticActivationService(db).activate(
                ctx,
                dataset_version_id=data_release.dataset_version_id,
                scenario_version="1.0.0",
                semantic_model_version_id=incompatible.semantic_model_version_id,
                idempotency_key="activate-incompatible",
            )
        assert exc.value.code == "SEMANTIC_VERSION_INCOMPATIBLE"


def test_resolver_fails_closed_without_active_semantic_version() -> None:
    with SessionLocal() as db:
        ctx = identity()
        dataset, data_release = dataset_version(db, ctx)
        SemanticActivationService(db).activate(
            ctx,
            dataset_version_id=data_release.dataset_version_id,
            scenario_version="1.0.0",
            semantic_model_version_id=None,
            idempotency_key="dataset-only",
        )
        with pytest.raises(SemanticRegistryError) as exc:
            ActiveSemanticResolver(db).resolve(
                ctx, scenario_id="scenario-a", dataset_code="operations"
            )
        assert exc.value.code == "NO_ACTIVE_SEMANTIC_VERSION"
