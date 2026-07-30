from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.semantic import SemanticField, SemanticTable
from app.platform.query_engine import QueryContext
from app.platform.semantic_registry import ActiveSemanticContext


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
    tables = tuple(db.scalars(
        select(SemanticTable).where(
            SemanticTable.semantic_model_version_id
            == platform_context.semantic_model_version_id
        )
    ).all())
    relation_columns: dict[str, tuple[str, ...]] = {}
    for table in tables:
        fields = tuple(db.scalars(
            select(SemanticField).where(
                SemanticField.semantic_table_id == table.semantic_table_id
            ).order_by(SemanticField.code)
        ).all())
        relation_columns[table.physical_binding] = tuple(
            field.physical_field
            for field in fields
            if field.classification not in {"restricted", "sensitive"}
        )
    source_binding = platform_context.source_binding
    datasource_id = source_binding.get("sqlbot_datasource_id")
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
        execution_mode=execution_mode,
        run_id=run_id,
        max_rows=500,
    )
