import hashlib
import json
from collections import OrderedDict
from copy import deepcopy
from threading import RLock

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.models import SQLBotSourceBindingRelease
from app.models.semantic import (
    SemanticDimension,
    SemanticField,
    SemanticMetric,
    SemanticRelationship,
    SemanticTable,
    SemanticTimeDimension,
)
from app.platform.query_engine import QueryContext
from app.platform.semantic_registry import ActiveSemanticContext
from app.query_engines.sqlbot.prompt_context import authorized_examples


_CATALOG_CACHE_MAX_SIZE = 32
_catalog_cache_lock = RLock()
_catalog_cache: OrderedDict[
    tuple[object, ...],
    tuple[dict[str, tuple[str, ...]], dict],
] = OrderedDict()


def _catalog_cache_key(
    db: Session,
    platform_context: ActiveSemanticContext,
    active_binding: SQLBotSourceBindingRelease | None,
) -> tuple[object, ...]:
    binding_json = active_binding.binding_json if active_binding else "{}"
    return (
        db.get_bind(),
        platform_context.tenant_id,
        platform_context.workspace_id,
        platform_context.scenario_id,
        platform_context.semantic_model_version_id,
        platform_context.dataset_version_id,
        active_binding.binding_release_id if active_binding else None,
        active_binding.version if active_binding else None,
        hashlib.sha256(binding_json.encode()).hexdigest(),
    )


def _cached_catalog(
    key: tuple[object, ...],
) -> tuple[dict[str, tuple[str, ...]], dict] | None:
    with _catalog_cache_lock:
        cached = _catalog_cache.get(key)
        if cached is None:
            return None
        _catalog_cache.move_to_end(key)
        return deepcopy(cached)


def _remember_catalog(
    key: tuple[object, ...],
    relation_columns: dict[str, tuple[str, ...]],
    prompt_context: dict,
) -> None:
    # Only immutable, published semantic catalog data is cached. Identity,
    # ACTIVE pointer resolution, permission checks, guards, and execution remain
    # request-scoped. Deep copies prevent callers from mutating shared state.
    with _catalog_cache_lock:
        _catalog_cache[key] = deepcopy((relation_columns, prompt_context))
        _catalog_cache.move_to_end(key)
        while len(_catalog_cache) > _CATALOG_CACHE_MAX_SIZE:
            _catalog_cache.popitem(last=False)


def build_query_context(
    db: Session,
    *,
    conversation_id: str,
    platform_context: ActiveSemanticContext | None,
    run_id: str | None = None,
) -> QueryContext:
    if platform_context is None:
        return QueryContext(
            conversation_id=conversation_id,
            scenario_version="legacy-0.1.0",
            semantic_version="legacy-0.1.0",
            semantic_model_version_id="legacy-disabled",
            dataset_version="legacy-platform-facts",
            dataset_version_id="legacy-disabled",
            datasource_id=None,
            allowed_relations={},
            execution_mode="upstream_readonly",
            run_id=run_id,
            max_rows=500,
        )
    active_binding = db.scalar(select(SQLBotSourceBindingRelease).where(
        SQLBotSourceBindingRelease.scenario_id == platform_context.scenario_id,
        SQLBotSourceBindingRelease.status == "ACTIVE",
    ).order_by(SQLBotSourceBindingRelease.version.desc()))
    binding_payload = json.loads(active_binding.binding_json) if active_binding else {}
    approved_relations = set(binding_payload.get("approved_relations") or ())
    cache_key = _catalog_cache_key(db, platform_context, active_binding)
    cached = _cached_catalog(cache_key)
    if cached is not None:
        relation_columns, prompt_context = cached
        source_binding = platform_context.source_binding
        datasource_id = (
            active_binding.datasource_id
            if active_binding is not None
            else source_binding.get("sqlbot_datasource_id")
        )
        return QueryContext(
            conversation_id=conversation_id,
            scenario_version=platform_context.scenario_version,
            semantic_version=platform_context.semantic_version,
            semantic_model_version_id=platform_context.semantic_model_version_id,
            dataset_version=str(platform_context.dataset_version),
            dataset_version_id=platform_context.dataset_version_id,
            datasource_id=(
                str(datasource_id) if datasource_id is not None else None
            ),
            allowed_relations=relation_columns,
            prompt_context=prompt_context,
            data_classification=str(
                binding_payload.get(
                    "data_classification", platform_context.data_classification
                )
            ),
            execution_mode=str(
                source_binding.get("sqlbot_execution_mode", "upstream_readonly")
            ),
            run_id=run_id,
            max_rows=500,
        )
    tables = tuple(db.scalars(
        select(SemanticTable).where(
            SemanticTable.semantic_model_version_id
            == platform_context.semantic_model_version_id
        )
    ).all())
    if approved_relations:
        tables = tuple(table for table in tables if table.physical_binding in approved_relations)
    relation_columns: dict[str, tuple[str, ...]] = {}
    authorized_tables: list[dict] = []
    table_bindings = {table.code: table.physical_binding for table in tables}
    fields_by_table: dict[str, list[SemanticField]] = {
        table.semantic_table_id: [] for table in tables
    }
    if fields_by_table:
        fields = tuple(db.scalars(
            select(SemanticField).where(
                SemanticField.semantic_table_id.in_(tuple(fields_by_table))
            ).order_by(
                SemanticField.semantic_table_id,
                SemanticField.code,
            )
        ).all())
        for field in fields:
            fields_by_table[field.semantic_table_id].append(field)
    for table in tables:
        fields = tuple(fields_by_table[table.semantic_table_id])
        relation_columns[table.physical_binding] = tuple(
            field.physical_field
            for field in fields
            if field.classification not in {"restricted", "sensitive"}
        )
        authorized_tables.append({
            "code": table.code,
            "name": table.name,
            "relation": table.physical_binding,
            "fields": [
                {
                    "code": field.code,
                    "name": field.name,
                    "physical_field": field.physical_field,
                    "data_type": field.data_type,
                }
                for field in fields
                if field.classification not in {"restricted", "sensitive"}
            ],
        })
    version_id = platform_context.semantic_model_version_id
    all_metrics = tuple(db.scalars(select(SemanticMetric).where(
        SemanticMetric.semantic_model_version_id == version_id
    ).order_by(SemanticMetric.code)).all())
    allowed_table_codes = set(table_bindings)
    safe_metric_codes: set[str] = set()
    unresolved = list(all_metrics)
    while unresolved:
        remaining = []
        changed = False
        for item in unresolved:
            lineage = json.loads(item.lineage_json)
            field_tables = {
                str(field).split(".", 1)[0]
                for field in lineage.get("fields", ())
                if "." in str(field)
            }
            dependencies = set(lineage.get("metrics", ()))
            if field_tables and field_tables.issubset(allowed_table_codes):
                safe_metric_codes.add(item.code)
                changed = True
            elif dependencies and dependencies.issubset(safe_metric_codes):
                safe_metric_codes.add(item.code)
                changed = True
            else:
                remaining.append(item)
        if not changed:
            break
        unresolved = remaining
    metrics = tuple(item for item in all_metrics if item.code in safe_metric_codes)
    dimensions = tuple(db.scalars(select(SemanticDimension).where(
        SemanticDimension.semantic_model_version_id == version_id
    ).order_by(SemanticDimension.code)).all())
    dimensions = tuple(
        item for item in dimensions
        if item.field_ref.split(".", 1)[0] in allowed_table_codes
    )
    # A published dimension is itself an allowlisted semantic field.  Include
    # its physical field when an older model release omitted the duplicate
    # SemanticField row; this keeps the published dimension and SQL policy in
    # sync without discovering arbitrary database columns.
    table_by_code = {table.code: table for table in tables}
    authorized_by_code = {item["code"]: item for item in authorized_tables}
    for dimension in dimensions:
        table_code, physical_field = dimension.field_ref.split(".", 1)
        table = table_by_code.get(table_code)
        if table is None:
            continue
        columns = list(relation_columns[table.physical_binding])
        if physical_field not in columns:
            columns.append(physical_field)
            relation_columns[table.physical_binding] = tuple(sorted(columns))
        table_prompt = authorized_by_code[table_code]
        if not any(
            item["physical_field"] == physical_field
            for item in table_prompt["fields"]
        ):
            table_prompt["fields"].append({
                "code": dimension.code,
                "name": dimension.name,
                "physical_field": physical_field,
                "data_type": dimension.data_type,
            })
    relationships = tuple(db.scalars(select(SemanticRelationship).where(
        SemanticRelationship.semantic_model_version_id == version_id,
        SemanticRelationship.status == "PUBLISHED",
    ).order_by(SemanticRelationship.code)).all())
    relationships = tuple(
        item for item in relationships
        if item.source_table in allowed_table_codes
        and item.target_table in allowed_table_codes
    )
    time_dimensions = tuple(db.scalars(select(SemanticTimeDimension).where(
        SemanticTimeDimension.semantic_model_version_id == version_id
    ).order_by(SemanticTimeDimension.code)).all())
    time_dimensions = tuple(
        item for item in time_dimensions
        if item.field_ref.split(".", 1)[0] in allowed_table_codes
    )
    prompt_context = {
        "dataset_period_start": platform_context.dataset_period_start,
        "dataset_period_end_exclusive": platform_context.dataset_period_end_exclusive,
        "authorized_tables": authorized_tables,
        "metrics": [
            {
                "code": item.code,
                "name": item.name,
                "aliases": json.loads(item.aliases_json),
                "expression": item.expression,
                "aggregation": item.aggregation,
                "time_field": item.time_field,
                "lineage": json.loads(item.lineage_json),
                "supported_dimensions": json.loads(item.supported_dimensions_json),
            }
            for item in metrics
        ],
        "dimensions": [
            {
                "code": item.code,
                "name": item.name,
                "aliases": json.loads(item.aliases_json),
                "field_ref": item.field_ref,
                "data_type": item.data_type,
            }
            for item in dimensions
        ],
        "relationships": [
            {
                "code": item.code,
                "source_table": table_bindings.get(item.source_table, item.source_table),
                "source_fields": json.loads(item.source_fields_json),
                "target_table": table_bindings.get(item.target_table, item.target_table),
                "target_fields": json.loads(item.target_fields_json),
                "cardinality": item.cardinality,
                "join_type": item.join_type,
            }
            for item in relationships
        ],
        "time_dimensions": [
            {
                "code": item.code,
                "field_ref": item.field_ref,
                "timezone": item.timezone,
                "grains": json.loads(item.grains_json),
            }
            for item in time_dimensions
        ],
        "sql_examples": list(authorized_examples(
            platform_context.scenario_id,
            relation_columns,
        )),
    }
    _remember_catalog(cache_key, relation_columns, prompt_context)
    source_binding = platform_context.source_binding
    datasource_id = (
        active_binding.datasource_id
        if active_binding is not None
        else source_binding.get("sqlbot_datasource_id")
    )
    execution_mode = str(
        source_binding.get("sqlbot_execution_mode", "upstream_readonly")
    )
    return QueryContext(
        conversation_id=conversation_id,
        scenario_version=platform_context.scenario_version,
        semantic_version=platform_context.semantic_version,
        semantic_model_version_id=platform_context.semantic_model_version_id,
        dataset_version=str(platform_context.dataset_version),
        dataset_version_id=platform_context.dataset_version_id,
        datasource_id=str(datasource_id) if datasource_id is not None else None,
        allowed_relations=relation_columns,
        prompt_context=prompt_context,
        data_classification=str(
            binding_payload.get(
                "data_classification", platform_context.data_classification
            )
        ),
        execution_mode=execution_mode,
        run_id=run_id,
        max_rows=500,
    )
