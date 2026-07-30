from sqlalchemy.orm import Session

from app.models.auth import User
from app.platform.identity import IdentityContext, IdentityContextFactory
from app.platform.scenario_packages import ScenarioRegistry
from app.platform.semantic_registry import ActiveSemanticContext, ActiveSemanticResolver
from app.scenarios.sales_ops.package_adapter import DATASET_CODE, SCENARIO_ID


def resolve_sales_ops_context(
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
        "order_fact": "sales_order",
        "order_item_fact": "sales_order_item",
        "customer_dimension": "sales_customer",
        "product_dimension": "sales_product",
        "category_dimension": "sales_product_category",
        "channel_dimension": "sales_channel",
        "region_dimension": "sales_region",
        "salesperson_dimension": "salesperson",
        "date_dimension": "sales_business_date",
    }
    if semantic.source_binding.get("relations") != expected_relations:
        raise RuntimeError("ACTIVE_SOURCE_BINDING_UNSUPPORTED")
    return identity, semantic
