from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.platform_data import (
    DatasetVersion,
    ReleaseRecord,
    RollbackRecord,
)
from app.platform.dataset_release import (
    ActiveDatasetResolver,
    DatasetReleaseError,
    DatasetVersionService,
    ReleaseService,
    RollbackService,
    SemanticActivationService,
)
from app.platform.identity import IdentityContext


def identity(subject: str = "user-1", tenant: str = "tenant-1") -> IdentityContext:
    return IdentityContext(
        subject_id=subject,
        tenant_id=tenant,
        org_id="org-1",
        workspace_id="workspace-1",
        roles=("analyst_admin",),
        groups=(),
        data_scopes=("all",),
        auth_strength="local-test",
        issued_at=datetime.now(UTC),
        request_id=f"request-{subject}",
    )


def create_dataset(db, ctx: IdentityContext):
    return DatasetVersionService(db).create_dataset(
        ctx,
        code="operations",
        name="Operations",
        scenario_id="scenario-a",
        owner_subject_id=ctx.subject_id,
        data_classification="simulated",
    )


def create_version(db, ctx: IdentityContext, dataset_id: str, key: str, quality: str = "PASSED"):
    return DatasetVersionService(db).create_version(
        ctx,
        dataset_id=dataset_id,
        mapping=[{"source": "source_id", "target": "entity_id"}],
        schema={"fields": [{"name": "entity_id", "type": "string"}]},
        source_binding={"relations": ["semantic.fact_view"]},
        source_version=f"source-{key}",
        quality_run_id=f"quality-{key}",
        quality_status=quality,
        quality_rules=[{"rule": "required", "status": quality}],
        row_count=3,
        period_start="2026-01-01",
        period_end_exclusive="2026-02-01",
        compatible_semantic_range=">=1.0.0,<2.0.0",
        idempotency_key=f"create-{key}",
    )


def publish_version(db, ctx: IdentityContext, version: DatasetVersion):
    service = ReleaseService(db)
    service.submit(ctx, version.dataset_version_id)
    service.decide(ctx, version.dataset_version_id, approved=True)
    return service.publish(
        ctx,
        version.dataset_version_id,
        idempotency_key=f"publish-{version.dataset_version_id}",
    )


def test_release_is_immutable_idempotent_and_not_implicitly_active() -> None:
    with SessionLocal() as db:
        ctx = identity()
        dataset = create_dataset(db, ctx)
        first = create_version(db, ctx, dataset.dataset_id, "v1")
        repeated = create_version(db, ctx, dataset.dataset_id, "v1")
        assert repeated.dataset_version_id == first.dataset_version_id

        published = publish_version(db, ctx, first)
        assert published.status == "PUBLISHED"
        assert published.published_at is not None
        assert db.scalar(
            select(func.count()).select_from(ReleaseRecord).where(
                ReleaseRecord.action == "PUBLISH"
            )
        ) == 1
        with pytest.raises(DatasetReleaseError) as exc:
            DatasetVersionService(db).assert_content_mutable(published)
        assert exc.value.code == "IMMUTABLE_VERSION"


def test_quality_failure_and_rejection_cannot_be_published() -> None:
    with SessionLocal() as db:
        ctx = identity()
        dataset = create_dataset(db, ctx)
        failed = create_version(db, ctx, dataset.dataset_id, "failed", quality="FAILED")
        with pytest.raises(DatasetReleaseError) as exc:
            ReleaseService(db).submit(ctx, failed.dataset_version_id)
        assert exc.value.code == "INVALID_STATE"

        passed = create_version(db, ctx, dataset.dataset_id, "rejected")
        service = ReleaseService(db)
        service.submit(ctx, passed.dataset_version_id)
        service.decide(ctx, passed.dataset_version_id, approved=False, reason="quality owner rejected")
        with pytest.raises(DatasetReleaseError) as exc:
            service.publish(ctx, passed.dataset_version_id, idempotency_key="reject-publish")
        assert exc.value.code == "NOT_APPROVED"


def test_activation_is_atomic_unique_and_idempotent() -> None:
    with SessionLocal() as db:
        ctx = identity()
        dataset = create_dataset(db, ctx)
        first = publish_version(db, ctx, create_version(db, ctx, dataset.dataset_id, "v1"))
        second = publish_version(db, ctx, create_version(db, ctx, dataset.dataset_id, "v2"))
        activation = SemanticActivationService(db)

        pointer = activation.activate(
            ctx,
            dataset_version_id=first.dataset_version_id,
            scenario_version="1.0.0",
            semantic_model_version_id=None,
            idempotency_key="activate-v1",
        )
        repeated = activation.activate(
            ctx,
            dataset_version_id=first.dataset_version_id,
            scenario_version="1.0.0",
            semantic_model_version_id=None,
            idempotency_key="activate-v1-repeat",
        )
        assert repeated.activation_id == pointer.activation_id

        switched = activation.activate(
            ctx,
            dataset_version_id=second.dataset_version_id,
            scenario_version="1.0.0",
            semantic_model_version_id=None,
            idempotency_key="activate-v2",
        )
        assert switched.active_dataset_version_id == second.dataset_version_id
        assert db.get(DatasetVersion, first.dataset_version_id).status == "SUPERSEDED"
        assert db.get(DatasetVersion, second.dataset_version_id).status == "ACTIVE"
        active_count = db.scalar(select(func.count()).select_from(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset.dataset_id,
            DatasetVersion.status == "ACTIVE",
        ))
        assert active_count == 1
        resolved = ActiveDatasetResolver(db).resolve(
            ctx, scenario_id="scenario-a", dataset_code="operations"
        )
        assert resolved[1].dataset_version_id == second.dataset_version_id


def test_failed_activation_preserves_previous_active_version() -> None:
    with SessionLocal() as db:
        ctx = identity()
        dataset = create_dataset(db, ctx)
        first = publish_version(db, ctx, create_version(db, ctx, dataset.dataset_id, "v1"))
        second = publish_version(db, ctx, create_version(db, ctx, dataset.dataset_id, "v2"))
        service = SemanticActivationService(db)
        service.activate(
            ctx,
            dataset_version_id=first.dataset_version_id,
            scenario_version="1.0.0",
            semantic_model_version_id=None,
            idempotency_key="activate-v1",
        )
        with pytest.raises(RuntimeError, match="injected"):
            service.activate(
                ctx,
                dataset_version_id=second.dataset_version_id,
                scenario_version="1.0.0",
                semantic_model_version_id=None,
                idempotency_key="activate-v2-fail",
                failure_hook=lambda: (_ for _ in ()).throw(RuntimeError("injected")),
            )
        current = service.current(ctx, scenario_id="scenario-a", dataset_id=dataset.dataset_id)
        assert current.active_dataset_version_id == first.dataset_version_id
        assert db.get(DatasetVersion, first.dataset_version_id).status == "ACTIVE"
        assert db.get(DatasetVersion, second.dataset_version_id).status == "PUBLISHED"


def test_rollback_creates_audit_is_idempotent_and_failure_is_atomic() -> None:
    with SessionLocal() as db:
        ctx = identity()
        dataset = create_dataset(db, ctx)
        first = publish_version(db, ctx, create_version(db, ctx, dataset.dataset_id, "v1"))
        second = publish_version(db, ctx, create_version(db, ctx, dataset.dataset_id, "v2"))
        activation = SemanticActivationService(db)
        activation.activate(
            ctx,
            dataset_version_id=first.dataset_version_id,
            scenario_version="1.0.0",
            semantic_model_version_id=None,
            idempotency_key="activate-v1",
        )
        activation.activate(
            ctx,
            dataset_version_id=second.dataset_version_id,
            scenario_version="1.0.0",
            semantic_model_version_id=None,
            idempotency_key="activate-v2",
        )
        rollback = RollbackService(db)
        record = rollback.rollback(
            ctx,
            scenario_id="scenario-a",
            dataset_id=dataset.dataset_id,
            target_dataset_version_id=first.dataset_version_id,
            reason="validated rollback",
            idempotency_key="rollback-v1",
        )
        repeated = rollback.rollback(
            ctx,
            scenario_id="scenario-a",
            dataset_id=dataset.dataset_id,
            target_dataset_version_id=first.dataset_version_id,
            reason="validated rollback",
            idempotency_key="rollback-v1",
        )
        assert repeated.rollback_record_id == record.rollback_record_id
        assert db.scalar(select(func.count()).select_from(RollbackRecord)) == 1
        assert db.scalar(select(func.count()).select_from(ReleaseRecord).where(
            ReleaseRecord.action == "ROLLBACK"
        )) == 1
        assert activation.current(
            ctx, scenario_id="scenario-a", dataset_id=dataset.dataset_id
        ).active_dataset_version_id == first.dataset_version_id

        with pytest.raises(RuntimeError, match="injected"):
            rollback.rollback(
                ctx,
                scenario_id="scenario-a",
                dataset_id=dataset.dataset_id,
                target_dataset_version_id=second.dataset_version_id,
                reason="must remain atomic",
                idempotency_key="rollback-v2-fail",
                failure_hook=lambda: (_ for _ in ()).throw(RuntimeError("injected")),
            )
        assert activation.current(
            ctx, scenario_id="scenario-a", dataset_id=dataset.dataset_id
        ).active_dataset_version_id == first.dataset_version_id


def test_tenant_scope_is_not_client_overridable() -> None:
    with SessionLocal() as db:
        owner = identity()
        outsider = identity("user-2", "tenant-2")
        dataset = create_dataset(db, owner)
        version = create_version(db, owner, dataset.dataset_id, "v1")
        with pytest.raises(DatasetReleaseError) as exc:
            ReleaseService(db).submit(outsider, version.dataset_version_id)
        assert exc.value.code == "DATASET_NOT_FOUND"
