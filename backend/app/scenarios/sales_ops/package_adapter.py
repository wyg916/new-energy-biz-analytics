from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.platform_data import DatasetVersion
from app.models.sales import SalesOrder
from app.models.semantic import SemanticModelVersion
from app.platform.dataset_release import (
    DatasetVersionService,
    ReleaseService,
    SemanticActivationService,
)
from app.platform.identity import IdentityContext
from app.platform.scenario_packages import (
    ScenarioPackage,
    ScenarioPackageLoader,
    ScenarioRegistry,
    ScenarioValidator,
)
from app.platform.semantic_registry import SemanticModelRegistry
from app.scenarios.sales_ops.seed import (
    DEFAULT_ORDER_COUNT,
    PERIOD_END_EXCLUSIVE,
    PERIOD_START,
    SEED_RUN_ID,
)

SCENARIO_ID = "sales_ops"
DATASET_CODE = "sales_operations"


def semantic_definition(package: ScenarioPackage) -> dict:
    models = package.documents["data_models.yaml"]
    dimensions = package.documents["dimensions.yaml"]
    relationships = package.documents["relationships.yaml"]
    metrics = package.documents["metrics.yaml"]
    permissions = package.documents["permissions.yaml"]
    return {
        "metadata": {
            "scenario_id": package.scenario_id,
            "scenario_version": package.version,
            "data_classification": package.manifest["data_classification"],
        },
        "tables": models["tables"],
        "fields": models["fields"],
        "metrics": metrics["metrics"],
        "dimensions": [
            {
                **item,
                "permission_policy": {"scope": "authorized_sales_scope"},
                "lineage": {"field": item["field_ref"]},
            }
            for item in dimensions["dimensions"]
        ],
        "relationships": relationships["relationships"],
        "time_dimensions": models["time_dimensions"],
        "filters": models["filters"],
        "policies": permissions["policies"],
    }


def install_sales_ops_foundation(
    db: Session,
    identity: IdentityContext,
    *,
    scenario_root: str | None = None,
    expected_order_count: int = DEFAULT_ORDER_COUNT,
) -> dict:
    package = ScenarioPackageLoader(scenario_root).load(SCENARIO_ID)
    registry = ScenarioRegistry(db)
    registry.validate(identity, package, ScenarioValidator())
    registry.publish(identity, package.scenario_id, package.version)
    scenario_release = registry.activate(
        identity,
        package.scenario_id,
        package.version,
    )
    order_count = int(
        db.scalar(select(func.count()).select_from(SalesOrder)) or 0
    )
    if order_count != expected_order_count:
        raise RuntimeError(
            "SALES_ORDER_COUNT_MISMATCH: simulated sales seed is incomplete"
        )
    definition = semantic_definition(package)
    dataset_service = DatasetVersionService(db)
    dataset = dataset_service.create_dataset(
        identity,
        code=package.manifest["dataset_code"],
        name="模拟销售经营事实数据集",
        scenario_id=package.scenario_id,
        owner_subject_id=identity.subject_id,
        data_classification="simulated",
        source_id=None,
    )
    version = db.scalar(select(DatasetVersion).where(
        DatasetVersion.dataset_id == dataset.dataset_id,
        DatasetVersion.idempotency_key
        == f"{package.scenario_id}:{package.version}:dataset",
    ))
    if version is None:
        version = dataset_service.create_version(
            identity,
            dataset_id=dataset.dataset_id,
            mapping=[
                {
                    "semantic_table": table["code"],
                    "physical_binding": table["physical_binding"],
                }
                for table in definition["tables"]
            ],
            schema={
                "tables": definition["tables"],
                "fields": definition["fields"],
            },
            source_binding={
                "relations": {
                    table["code"]: table["physical_binding"]
                    for table in definition["tables"]
                },
                "source": "platform_database",
                "data_classification": "simulated",
                "sqlbot_execution_mode": "upstream_readonly",
            },
            source_version=SEED_RUN_ID,
            quality_run_id=f"{package.scenario_id}:{package.version}:quality",
            quality_status="PASSED",
            quality_rules=[
                {"code": "scenario_package_valid", "status": "PASSED"},
                {
                    "code": "metric_count",
                    "status": "PASSED",
                    "expected": 12,
                    "actual": len(package.documents["metrics.yaml"]["metrics"]),
                },
                {
                    "code": "simulated_order_count",
                    "status": "PASSED",
                    "expected": expected_order_count,
                    "actual": order_count,
                },
                {"code": "simulated_data_label", "status": "PASSED"},
            ],
            row_count=order_count,
            period_start=PERIOD_START.isoformat(),
            period_end_exclusive=PERIOD_END_EXCLUSIVE.isoformat(),
            compatible_semantic_range=">=1.0.0,<2.0.0",
            idempotency_key=f"{package.scenario_id}:{package.version}:dataset",
        )
        release = ReleaseService(db)
        release.submit(identity, version.dataset_version_id)
        release.decide(identity, version.dataset_version_id, approved=True)
        release.publish(
            identity,
            version.dataset_version_id,
            idempotency_key=f"{package.scenario_id}:{package.version}:publish",
        )

    semantic_registry = SemanticModelRegistry(db)
    model = semantic_registry.register_model(
        identity,
        scenario_id=package.scenario_id,
        code=package.manifest["semantic_model_code"],
        name="模拟销售经营语义模型",
        owner_subject_id=identity.subject_id,
    )
    semantic_version = db.scalar(select(SemanticModelVersion).where(
        SemanticModelVersion.semantic_model_id == model.semantic_model_id,
        SemanticModelVersion.version == package.manifest["semantic_version"],
    ))
    if semantic_version is None:
        semantic_version = semantic_registry.register_version(
            identity,
            semantic_model_id=model.semantic_model_id,
            version=package.manifest["semantic_version"],
            scenario_version=package.version,
            contract_version="0.1",
            dataset_compatibility={package.manifest["dataset_code"]: {}},
            definition=definition,
        )
        semantic_registry.publish(
            identity,
            semantic_version.semantic_model_version_id,
            reviewer_subject_id=identity.subject_id,
        )
    activation = SemanticActivationService(db).activate(
        identity,
        dataset_version_id=version.dataset_version_id,
        scenario_version=package.version,
        semantic_model_version_id=semantic_version.semantic_model_version_id,
        idempotency_key=f"{package.scenario_id}:{package.version}:activate",
    )
    return {
        "scenario_id": scenario_release.scenario_id,
        "scenario_version": scenario_release.version,
        "scenario_status": scenario_release.status,
        "dataset_id": dataset.dataset_id,
        "dataset_version_id": version.dataset_version_id,
        "dataset_version": version.version,
        "semantic_model_version_id": semantic_version.semantic_model_version_id,
        "semantic_version": semantic_version.version,
        "activation_id": activation.activation_id,
        "data_classification": "simulated",
        "order_count": order_count,
        "metric_count": len(package.documents["metrics.yaml"]["metrics"]),
        "package_checksum": package.checksum,
    }
