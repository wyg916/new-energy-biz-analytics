import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.platform_data import (
    DatasetVersion,
    MappingVersion,
    PlatformDataset,
    QualityResult,
    ReleaseRecord,
    ReviewRecord,
    RollbackRecord,
    SemanticActivation,
)
from app.platform.identity import IdentityContext

LOCKED_CONTENT_STATUSES = {"PUBLISHED", "ACTIVE", "SUPERSEDED", "RETIRED"}


class DatasetReleaseError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class DatasetVersionService:
    def __init__(self, db: Session):
        self.db = db

    def create_dataset(
        self,
        identity: IdentityContext,
        *,
        code: str,
        name: str,
        scenario_id: str,
        owner_subject_id: str,
        data_classification: str,
        source_id: str | None = None,
        dataset_id: str | None = None,
    ) -> PlatformDataset:
        existing = self.db.scalar(select(PlatformDataset).where(
            PlatformDataset.tenant_id == identity.tenant_id,
            PlatformDataset.workspace_id == identity.workspace_id,
            PlatformDataset.scenario_id == scenario_id,
            PlatformDataset.code == code,
        ))
        if existing:
            return existing
        dataset = PlatformDataset(
            dataset_id=dataset_id or f"DS-{uuid4()}",
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            scenario_id=scenario_id,
            code=code,
            name=name,
            source_id=source_id,
            owner_subject_id=owner_subject_id,
            data_classification=data_classification,
            status="ENABLED",
        )
        self.db.add(dataset)
        self.db.commit()
        return dataset

    def create_version(
        self,
        identity: IdentityContext,
        *,
        dataset_id: str,
        mapping: list[dict],
        schema: dict,
        source_binding: dict,
        source_version: str,
        quality_run_id: str,
        quality_status: str,
        quality_rules: list[dict],
        row_count: int,
        period_start: str | None,
        period_end_exclusive: str | None,
        compatible_semantic_range: str,
        idempotency_key: str,
    ) -> DatasetVersion:
        dataset = self._scoped_dataset(identity, dataset_id)
        dataset = self.db.scalar(
            select(PlatformDataset)
            .where(PlatformDataset.dataset_id == dataset.dataset_id)
            .with_for_update()
        )
        existing = self.db.scalar(select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.idempotency_key == idempotency_key,
        ))
        if existing:
            return existing
        next_version = int(self.db.scalar(
            select(func.coalesce(func.max(DatasetVersion.version), 0)).where(
                DatasetVersion.dataset_id == dataset_id
            )
        ) or 0) + 1
        mapping_json = _canonical(mapping)
        quality_json = _canonical(quality_rules)
        mapping_checksum = _digest(mapping)
        mapping_version = self.db.scalar(select(MappingVersion).where(
            MappingVersion.dataset_id == dataset_id,
            MappingVersion.checksum == mapping_checksum,
        ))
        if mapping_version is None:
            next_mapping = int(self.db.scalar(
                select(func.coalesce(func.max(MappingVersion.version), 0)).where(
                    MappingVersion.dataset_id == dataset_id
                )
            ) or 0) + 1
            mapping_version = MappingVersion(
                mapping_version_id=f"MAP-{uuid4()}",
                dataset_id=dataset_id,
                version=next_mapping,
                mapping_json=mapping_json,
                checksum=mapping_checksum,
                status="PUBLISHED",
                created_by=identity.subject_id,
            )
            self.db.add(mapping_version)
        quality = QualityResult(
            quality_result_id=f"DQ-{uuid4()}",
            dataset_id=dataset_id,
            run_id=quality_run_id,
            status=quality_status,
            rules_json=quality_json,
            checksum=_digest(quality_rules),
            checked_by=identity.subject_id,
        )
        content = {
            "dataset_id": dataset_id,
            "version": next_version,
            "schema": schema,
            "source_binding": source_binding,
            "source_version": source_version,
            "mapping_checksum": mapping_version.checksum,
            "quality_checksum": quality.checksum,
            "row_count": row_count,
            "period_start": period_start,
            "period_end_exclusive": period_end_exclusive,
        }
        version = DatasetVersion(
            dataset_version_id=f"DSV-{uuid4()}",
            dataset_id=dataset_id,
            version=next_version,
            status="QUALITY_PASSED" if quality_status == "PASSED" else "QUALITY_FAILED",
            schema_json=_canonical(schema),
            source_binding_json=_canonical(source_binding),
            source_version=source_version,
            mapping_version_id=mapping_version.mapping_version_id,
            quality_result_id=quality.quality_result_id,
            checksum=_digest(content),
            row_count=row_count,
            period_start=period_start,
            period_end_exclusive=period_end_exclusive,
            compatible_semantic_range=compatible_semantic_range,
            idempotency_key=idempotency_key,
            created_by=identity.subject_id,
        )
        self.db.add_all([quality, version])
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(select(DatasetVersion).where(
                DatasetVersion.dataset_id == dataset_id,
                DatasetVersion.idempotency_key == idempotency_key,
            ))
            if existing:
                return existing
            raise
        return version

    def assert_content_mutable(self, version: DatasetVersion) -> None:
        if version.status in LOCKED_CONTENT_STATUSES:
            raise DatasetReleaseError(
                "IMMUTABLE_VERSION",
                "已发布或已激活的数据集版本内容不可修改",
            )

    def _scoped_dataset(self, identity: IdentityContext, dataset_id: str) -> PlatformDataset:
        dataset = self.db.get(PlatformDataset, dataset_id)
        if (
            dataset is None
            or dataset.tenant_id != identity.tenant_id
            or dataset.workspace_id != identity.workspace_id
        ):
            raise DatasetReleaseError("DATASET_NOT_FOUND", "数据集不存在或不在当前工作区")
        return dataset


class ReleaseService:
    def __init__(self, db: Session):
        self.db = db

    def submit(self, identity: IdentityContext, dataset_version_id: str) -> ReviewRecord:
        version, dataset = self._scoped_version(identity, dataset_version_id)
        if version.status not in {"QUALITY_PASSED", "PENDING_APPROVAL"}:
            raise DatasetReleaseError("INVALID_STATE", "只有质量通过版本可以提交审核")
        existing = self.db.scalar(select(ReviewRecord).where(
            ReviewRecord.dataset_version_id == dataset_version_id
        ))
        if existing:
            return existing
        version.status = "PENDING_APPROVAL"
        review = ReviewRecord(
            review_record_id=f"REV-{uuid4()}",
            dataset_version_id=dataset_version_id,
            status="PENDING",
            requested_by=identity.subject_id,
        )
        self.db.add(review)
        self._audit(identity, dataset, version, "SUBMIT", "SUCCEEDED", None, f"submit:{dataset_version_id}")
        self.db.commit()
        return review

    def decide(
        self,
        identity: IdentityContext,
        dataset_version_id: str,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> ReviewRecord:
        version, dataset = self._scoped_version(identity, dataset_version_id)
        review = self.db.scalar(select(ReviewRecord).where(
            ReviewRecord.dataset_version_id == dataset_version_id
        ))
        if review is None or review.status != "PENDING" or version.status != "PENDING_APPROVAL":
            raise DatasetReleaseError("INVALID_STATE", "当前版本不处于待审批状态")
        review.status = "APPROVED" if approved else "REJECTED"
        review.decided_by = identity.subject_id
        review.decided_at = _now()
        review.reason = reason
        version.status = review.status
        self._audit(
            identity, dataset, version,
            "APPROVE" if approved else "REJECT",
            "SUCCEEDED",
            reason,
            f"decide:{dataset_version_id}:{review.status}",
        )
        self.db.commit()
        return review

    def publish(
        self,
        identity: IdentityContext,
        dataset_version_id: str,
        *,
        idempotency_key: str,
    ) -> DatasetVersion:
        version, dataset = self._scoped_version(identity, dataset_version_id)
        existing = self.db.scalar(select(ReleaseRecord).where(
            ReleaseRecord.idempotency_key == idempotency_key
        ))
        if existing:
            if existing.dataset_version_id != dataset_version_id or existing.action != "PUBLISH":
                raise DatasetReleaseError("IDEMPOTENCY_CONFLICT", "发布幂等键已用于其他操作")
            return version
        if version.status == "PUBLISHED":
            return version
        if version.status != "APPROVED":
            raise DatasetReleaseError("NOT_APPROVED", "未批准版本不得发布")
        version.status = "PUBLISHED"
        version.published_at = _now()
        self._audit(identity, dataset, version, "PUBLISH", "SUCCEEDED", None, idempotency_key)
        self.db.commit()
        return version

    def _scoped_version(
        self, identity: IdentityContext, dataset_version_id: str
    ) -> tuple[DatasetVersion, PlatformDataset]:
        version = self.db.get(DatasetVersion, dataset_version_id)
        if version is None:
            raise DatasetReleaseError("VERSION_NOT_FOUND", "数据集版本不存在")
        dataset = DatasetVersionService(self.db)._scoped_dataset(identity, version.dataset_id)
        return version, dataset

    def _audit(
        self,
        identity: IdentityContext,
        dataset: PlatformDataset,
        version: DatasetVersion,
        action: str,
        outcome: str,
        reason: str | None,
        idempotency_key: str,
    ) -> ReleaseRecord:
        record = ReleaseRecord(
            release_record_id=f"REL-{uuid4()}",
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            scenario_id=dataset.scenario_id,
            dataset_id=dataset.dataset_id,
            dataset_version_id=version.dataset_version_id,
            action=action,
            outcome=outcome,
            actor_subject_id=identity.subject_id,
            reason=reason,
            run_id=f"RUN-{uuid4()}",
            idempotency_key=idempotency_key,
        )
        self.db.add(record)
        return record


class SemanticActivationService:
    def __init__(self, db: Session):
        self.db = db

    def activate(
        self,
        identity: IdentityContext,
        *,
        dataset_version_id: str,
        scenario_version: str,
        semantic_model_version_id: str | None,
        idempotency_key: str,
        reason: str | None = None,
        failure_hook: Callable[[], None] | None = None,
    ) -> SemanticActivation:
        try:
            semantic_version = None
            semantic_model = None
            version = self.db.get(DatasetVersion, dataset_version_id)
            if version is None:
                raise DatasetReleaseError("VERSION_NOT_FOUND", "数据集版本不存在")
            dataset = self.db.scalar(
                select(PlatformDataset)
                .where(PlatformDataset.dataset_id == version.dataset_id)
                .with_for_update()
            )
            if (
                dataset is None
                or dataset.tenant_id != identity.tenant_id
                or dataset.workspace_id != identity.workspace_id
            ):
                raise DatasetReleaseError("DATASET_NOT_FOUND", "数据集不存在或不在当前工作区")
            if version.status not in {"PUBLISHED", "SUPERSEDED", "ACTIVE"}:
                raise DatasetReleaseError("NOT_PUBLISHED", "只有已发布版本可以激活")
            if semantic_model_version_id:
                from app.models.semantic import SemanticModel, SemanticModelVersion
                from app.platform.versioning import version_satisfies

                semantic_version = self.db.get(SemanticModelVersion, semantic_model_version_id)
                semantic_model = (
                    self.db.get(SemanticModel, semantic_version.semantic_model_id)
                    if semantic_version else None
                )
                if (
                    semantic_version is None
                    or semantic_model is None
                    or semantic_version.status not in {"PUBLISHED", "SUPERSEDED", "ACTIVE"}
                    or semantic_model.tenant_id != identity.tenant_id
                    or semantic_model.workspace_id != identity.workspace_id
                    or semantic_model.scenario_id != dataset.scenario_id
                    or semantic_version.scenario_version != scenario_version
                ):
                    raise DatasetReleaseError(
                        "SEMANTIC_VERSION_INVALID",
                        "语义版本未发布、范围不匹配或场景版本不兼容",
                    )
                if not version_satisfies(
                    semantic_version.version, version.compatible_semantic_range
                ):
                    raise DatasetReleaseError(
                        "SEMANTIC_VERSION_INCOMPATIBLE",
                        "数据集版本与语义版本不兼容",
                    )
            pointer = self.db.scalar(
                select(SemanticActivation).where(
                    SemanticActivation.tenant_id == identity.tenant_id,
                    SemanticActivation.workspace_id == identity.workspace_id,
                    SemanticActivation.scenario_id == dataset.scenario_id,
                    SemanticActivation.dataset_id == dataset.dataset_id,
                ).with_for_update()
            )
            if (
                pointer
                and pointer.active_dataset_version_id == dataset_version_id
                and pointer.active_semantic_model_version_id == semantic_model_version_id
                and pointer.scenario_version == scenario_version
            ):
                return pointer
            prior = self.db.get(DatasetVersion, pointer.active_dataset_version_id) if pointer else None
            if prior:
                prior.status = "SUPERSEDED"
                self.db.flush()
            if pointer and pointer.active_semantic_model_version_id:
                from app.models.semantic import SemanticModelVersion

                prior_semantic = self.db.get(
                    SemanticModelVersion, pointer.active_semantic_model_version_id
                )
                if (
                    prior_semantic
                    and prior_semantic.semantic_model_version_id != semantic_model_version_id
                ):
                    prior_semantic.status = "SUPERSEDED"
                    self.db.flush()
            version.status = "ACTIVE"
            if semantic_version:
                semantic_version.status = "ACTIVE"
            now = _now()
            if pointer is None:
                pointer = SemanticActivation(
                    activation_id=f"ACT-{uuid4()}",
                    tenant_id=identity.tenant_id,
                    workspace_id=identity.workspace_id,
                    scenario_id=dataset.scenario_id,
                    scenario_version=scenario_version,
                    dataset_id=dataset.dataset_id,
                    active_dataset_version_id=dataset_version_id,
                    active_semantic_model_version_id=semantic_model_version_id,
                    lock_version=1,
                    activated_by=identity.subject_id,
                    activated_at=now,
                )
                self.db.add(pointer)
            else:
                pointer.scenario_version = scenario_version
                pointer.active_dataset_version_id = dataset_version_id
                pointer.active_semantic_model_version_id = semantic_model_version_id
                pointer.lock_version += 1
                pointer.activated_by = identity.subject_id
                pointer.activated_at = now
            ReleaseService(self.db)._audit(
                identity,
                dataset,
                version,
                "ACTIVATE",
                "SUCCEEDED",
                reason,
                idempotency_key,
            )
            if failure_hook:
                failure_hook()
            self.db.commit()
            return pointer
        except Exception:
            self.db.rollback()
            raise

    def current(
        self,
        identity: IdentityContext,
        *,
        scenario_id: str,
        dataset_id: str,
    ) -> SemanticActivation:
        pointer = self.db.scalar(select(SemanticActivation).where(
            SemanticActivation.tenant_id == identity.tenant_id,
            SemanticActivation.workspace_id == identity.workspace_id,
            SemanticActivation.scenario_id == scenario_id,
            SemanticActivation.dataset_id == dataset_id,
        ))
        if pointer is None:
            raise DatasetReleaseError("NO_ACTIVE_VERSION", "当前工作区没有 ACTIVE 数据集版本")
        version = self.db.get(DatasetVersion, pointer.active_dataset_version_id)
        if version is None or version.status != "ACTIVE":
            raise DatasetReleaseError("STALE_ACTIVATION", "ACTIVE 指针与数据集版本状态不一致")
        return pointer


class RollbackService:
    def __init__(self, db: Session):
        self.db = db

    def rollback(
        self,
        identity: IdentityContext,
        *,
        scenario_id: str,
        dataset_id: str,
        target_dataset_version_id: str,
        reason: str,
        idempotency_key: str,
        failure_hook: Callable[[], None] | None = None,
    ) -> RollbackRecord:
        existing = self.db.scalar(select(RollbackRecord).where(
            RollbackRecord.idempotency_key == idempotency_key
        ))
        if existing:
            return existing
        try:
            dataset = self.db.scalar(
                select(PlatformDataset)
                .where(PlatformDataset.dataset_id == dataset_id)
                .with_for_update()
            )
            if (
                dataset is None
                or dataset.tenant_id != identity.tenant_id
                or dataset.workspace_id != identity.workspace_id
                or dataset.scenario_id != scenario_id
            ):
                raise DatasetReleaseError("DATASET_NOT_FOUND", "数据集不存在或不在当前工作区")
            pointer = self.db.scalar(
                select(SemanticActivation)
                .where(
                    SemanticActivation.tenant_id == identity.tenant_id,
                    SemanticActivation.workspace_id == identity.workspace_id,
                    SemanticActivation.scenario_id == scenario_id,
                    SemanticActivation.dataset_id == dataset_id,
                )
                .with_for_update()
            )
            if pointer is None:
                raise DatasetReleaseError("NO_ACTIVE_VERSION", "当前工作区没有 ACTIVE 数据集版本")
            previous_id = pointer.active_dataset_version_id
            if previous_id == target_dataset_version_id:
                raise DatasetReleaseError("ALREADY_ACTIVE", "目标版本已经是 ACTIVE")
            target = self.db.get(DatasetVersion, target_dataset_version_id)
            if (
                target is None
                or target.dataset_id != dataset_id
                or target.status not in {"PUBLISHED", "SUPERSEDED"}
            ):
                raise DatasetReleaseError("ROLLBACK_TARGET_INVALID", "回滚目标不是兼容的已发布版本")
            current = self.db.get(DatasetVersion, previous_id)
            if current is None:
                raise DatasetReleaseError("STALE_ACTIVATION", "当前 ACTIVE 版本不存在")
            current.status = "SUPERSEDED"
            self.db.flush()
            target.status = "ACTIVE"
            pointer.active_dataset_version_id = target_dataset_version_id
            pointer.lock_version += 1
            pointer.activated_by = identity.subject_id
            pointer.activated_at = _now()
            record = RollbackRecord(
                rollback_record_id=f"RB-{uuid4()}",
                activation_id=pointer.activation_id,
                from_dataset_version_id=previous_id,
                to_dataset_version_id=target_dataset_version_id,
                reason=reason,
                actor_subject_id=identity.subject_id,
                run_id=f"RUN-{uuid4()}",
                idempotency_key=idempotency_key,
            )
            self.db.add(record)
            ReleaseService(self.db)._audit(
                identity,
                dataset,
                target,
                "ROLLBACK",
                "SUCCEEDED",
                reason,
                f"release:{idempotency_key}",
            )
            if failure_hook:
                failure_hook()
            self.db.commit()
            return record
        except Exception:
            self.db.rollback()
            raise


class ActiveDatasetResolver:
    def __init__(self, db: Session):
        self.db = db

    def resolve(
        self,
        identity: IdentityContext,
        *,
        scenario_id: str,
        dataset_code: str,
    ) -> tuple[PlatformDataset, DatasetVersion, SemanticActivation]:
        dataset = self.db.scalar(select(PlatformDataset).where(
            PlatformDataset.tenant_id == identity.tenant_id,
            PlatformDataset.workspace_id == identity.workspace_id,
            PlatformDataset.scenario_id == scenario_id,
            PlatformDataset.code == dataset_code,
            PlatformDataset.status == "ENABLED",
        ))
        if dataset is None:
            raise DatasetReleaseError("DATASET_NOT_FOUND", "当前范围内数据集不存在")
        pointer = SemanticActivationService(self.db).current(
            identity, scenario_id=scenario_id, dataset_id=dataset.dataset_id
        )
        version = self.db.get(DatasetVersion, pointer.active_dataset_version_id)
        if version is None or version.status != "ACTIVE":
            raise DatasetReleaseError("NO_ACTIVE_VERSION", "没有可消费的 ACTIVE 数据集版本")
        return dataset, version, pointer
