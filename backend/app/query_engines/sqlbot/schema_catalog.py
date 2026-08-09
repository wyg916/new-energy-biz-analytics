from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.platform.query_engine import QueryContext


@dataclass(frozen=True)
class RetrievedSchema:
    catalog_version: str
    catalog_hash: str
    relations: dict[str, tuple[str, ...]]
    relationships: tuple[dict[str, Any], ...]
    metrics: tuple[dict[str, Any], ...]
    dimensions: tuple[dict[str, Any], ...]
    time_dimensions: tuple[dict[str, Any], ...]
    retrieval_terms: tuple[str, ...]
    authorized_tables: tuple[dict[str, Any], ...] = ()

    def as_prompt_context(self) -> dict[str, Any]:
        return {
            "schema_catalog_version": self.catalog_version,
            "schema_catalog_hash": self.catalog_hash,
            "authorized_tables": list(self.authorized_tables) or [
                {"relation": relation, "fields": list(columns)}
                for relation, columns in sorted(self.relations.items())
            ],
            "relationships": list(self.relationships),
            "metrics": list(self.metrics),
            "dimensions": list(self.dimensions),
            "time_dimensions": list(self.time_dimensions),
            "retrieval_terms": list(self.retrieval_terms),
        }


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[\w\u4e00-\u9fff]+", value, re.UNICODE)
        if len(token) > 1
    }


def _searchable(item: dict[str, Any]) -> set[str]:
    return _tokens(json.dumps(item, ensure_ascii=False, sort_keys=True))


def _relevant(question: str, terms: set[str], item: dict[str, Any]) -> bool:
    compact_question = re.sub(r"\s+", "", question.lower())
    searchable = _searchable(item)
    return bool(
        terms & searchable
        or any(token in compact_question for token in searchable if len(token) > 1)
    )


def build_schema_catalog(context: QueryContext) -> dict[str, Any]:
    """Build a request-scoped catalog from the published semantic allowlist."""
    prompt = context.prompt_context or {}
    catalog = {
        "version": "sqlbot-schema-4.1",
        "scenario_version": context.scenario_version,
        "semantic_version": context.semantic_version,
        "semantic_model_version_id": context.semantic_model_version_id,
        "dataset_version": context.dataset_version,
        "dataset_version_id": context.dataset_version_id,
        "relations": {
            relation: list(columns)
            for relation, columns in sorted(context.allowed_relations.items())
        },
        "relationships": prompt.get("relationships", []),
        "metrics": prompt.get("metrics", []),
        "dimensions": prompt.get("dimensions", []),
        "time_dimensions": prompt.get("time_dimensions", []),
    }
    raw = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    catalog["catalog_hash"] = hashlib.sha256(raw.encode()).hexdigest()
    return catalog


def retrieve_schema(question: str, context: QueryContext) -> RetrievedSchema:
    """Retrieve only relevant registered schema while retaining join endpoints."""
    catalog = build_schema_catalog(context)
    terms = _tokens(question)
    metrics = tuple(
        item for item in catalog["metrics"]
        if not terms or _relevant(question, terms, item)
    )
    dimensions = tuple(
        item for item in catalog["dimensions"]
        if not terms or _relevant(question, terms, item)
    )

    authorized_tables = tuple(
        item for item in (context.prompt_context or {}).get("authorized_tables", ())
        if isinstance(item, dict) and item.get("relation") in context.allowed_relations
    )
    table_code_to_relation = {
        str(item.get("code")): str(item.get("relation"))
        for item in authorized_tables
        if item.get("code") and item.get("relation")
    }

    def physical_relation(value: str) -> str:
        return table_code_to_relation.get(value, value)

    selected = set()
    for item in (*metrics, *dimensions):
        for key in ("field_ref", "time_field"):
            ref = item.get(key)
            if isinstance(ref, str) and "." in ref:
                selected.add(physical_relation(ref.split(".", 1)[0]))
        expression = item.get("expression")
        if isinstance(expression, str):
            for identifier in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.", expression):
                selected.add(physical_relation(identifier))

    for relation, columns in context.allowed_relations.items():
        column_terms = set().union(*(_tokens(column.replace("_", " ")) for column in columns)) if columns else set()
        if relation.lower() in question.lower() or terms & column_terms:
            selected.add(relation)

    relationships = tuple(catalog["relationships"])
    if not selected:
        selected = set(context.allowed_relations)

    relations = {
        relation: context.allowed_relations[relation]
        for relation in sorted(selected)
        if relation in context.allowed_relations
    }
    retained_relationships = tuple(
        item for item in relationships
        if item.get("source_table") in relations and item.get("target_table") in relations
    )
    authorized_tables = tuple(
        item for item in authorized_tables
        if item.get("relation") in relations
    )
    time_dimensions = tuple(
        item for item in catalog["time_dimensions"]
        if isinstance(item.get("field_ref"), str)
        and physical_relation(item["field_ref"].split(".", 1)[0]) in relations
    )
    return RetrievedSchema(
        catalog_version=catalog["version"],
        catalog_hash=catalog["catalog_hash"],
        relations=relations,
        relationships=retained_relationships,
        metrics=metrics,
        dimensions=dimensions,
        time_dimensions=time_dimensions,
        retrieval_terms=tuple(sorted(terms)),
        authorized_tables=authorized_tables,
    )
