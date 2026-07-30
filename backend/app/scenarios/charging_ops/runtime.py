from sqlalchemy.orm import Session

from app.models.auth import User
from app.platform.identity import IdentityContext, IdentityContextFactory
from app.platform.scenario_packages import ScenarioRegistry
from app.platform.semantic_registry import ActiveSemanticContext, ActiveSemanticResolver

SCENARIO_ID = "charging_ops"
DATASET_CODE = "charging_operations"


def resolve_charging_ops_context(
    db: Session,
    user: User,
    *,
    request_id: str | None = None,
) -> tuple[IdentityContext, ActiveSemanticContext]:
    identity = IdentityContextFactory.from_user(user, request_id=request_id)
    scenario = ScenarioRegistry(db).resolve(identity, SCENARIO_ID)
    semantic = ActiveSemanticResolver(db).resolve(
        identity,
        scenario_id=scenario.scenario_id,
        dataset_code=DATASET_CODE,
    )
    expected_relations = {
        "session_fact": "fact_charging_session",
        "energy_cost_fact": "fact_energy_cost",
        "operation_expense_fact": "fact_operation_expense",
        "status_event_fact": "fact_device_status_event",
        "station_dimension": "dim_station",
    }
    if semantic.source_binding.get("relations") != expected_relations:
        raise RuntimeError("ACTIVE_SOURCE_BINDING_UNSUPPORTED")
    return identity, semantic


def platform_version_metadata(context: ActiveSemanticContext) -> dict:
    return {
        "scenario_id": context.scenario_id,
        "scenario_version": context.scenario_version,
        "semantic_version": context.semantic_version,
        "semantic_model_version_id": context.semantic_model_version_id,
        "dataset_version": str(context.dataset_version),
        "dataset_version_id": context.dataset_version_id,
        "dataset_checksum": context.dataset_checksum,
        "query_source": "active_dataset_version",
        "semantic_activation_status": "ACTIVE",
    }
