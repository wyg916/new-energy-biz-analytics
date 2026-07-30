"""Add dual-engine routing, SQLBot session, and shadow evidence tables."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sqlbot_session_binding",
        sa.Column("binding_id", sa.String(length=64), nullable=False),
        sa.Column("binding_hash", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=96), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_version", sa.String(length=32), nullable=False),
        sa.Column("semantic_version", sa.String(length=32), nullable=False),
        sa.Column("dataset_version", sa.String(length=32), nullable=False),
        sa.Column("external_chat_id", sa.String(length=128), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("binding_id"),
        sa.UniqueConstraint(
            "binding_hash",
            name="uq_sqlbot_session_binding_hash",
        ),
    )
    op.create_index(
        "ix_sqlbot_session_binding_scope",
        "sqlbot_session_binding",
        ["tenant_id", "workspace_id", "subject_id", "scenario_id"],
    )

    op.create_table(
        "shadow_evaluation",
        sa.Column("shadow_evaluation_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=96), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.Text(), nullable=False),
        sa.Column("route_mode", sa.String(length=32), nullable=False),
        sa.Column("scenario", sa.String(length=64), nullable=False),
        sa.Column("scenario_version", sa.String(length=32), nullable=False),
        sa.Column("semantic_version", sa.String(length=32), nullable=False),
        sa.Column("dataset_version", sa.String(length=32), nullable=False),
        sa.Column("deterministic_sql", sa.Text(), nullable=True),
        sa.Column("sqlbot_sql", sa.Text(), nullable=True),
        sa.Column("deterministic_result_hash", sa.String(length=64), nullable=True),
        sa.Column("sqlbot_result_hash", sa.String(length=64), nullable=True),
        sa.Column("execution_accuracy", sa.Float(), nullable=True),
        sa.Column("metric_value_match", sa.Integer(), nullable=True),
        sa.Column("time_range_match", sa.Integer(), nullable=True),
        sa.Column("dimension_match", sa.Integer(), nullable=True),
        sa.Column("permission_result", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("trace_id", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("shadow_evaluation_id"),
    )
    for name, columns in (
        ("ix_shadow_evaluation_tenant_id", ["tenant_id"]),
        ("ix_shadow_evaluation_workspace_id", ["workspace_id"]),
        ("ix_shadow_evaluation_subject_id", ["subject_id"]),
        ("ix_shadow_evaluation_conversation_id", ["conversation_id"]),
        ("ix_shadow_evaluation_scenario", ["scenario"]),
        ("ix_shadow_evaluation_run_id", ["run_id"]),
        ("ix_shadow_evaluation_trace_id", ["trace_id"]),
        (
            "ix_shadow_evaluation_scope_created",
            ["tenant_id", "workspace_id", "scenario", "created_at"],
        ),
    ):
        op.create_index(name, "shadow_evaluation", columns)

    op.create_table(
        "query_route_decision",
        sa.Column("route_decision_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=96), nullable=False),
        sa.Column("route_decision", sa.String(length=64), nullable=False),
        sa.Column("route_reason", sa.String(length=160), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("scenario", sa.String(length=64), nullable=False),
        sa.Column("scenario_version", sa.String(length=32), nullable=False),
        sa.Column("semantic_version", sa.String(length=32), nullable=False),
        sa.Column("dataset_version", sa.String(length=32), nullable=False),
        sa.Column("feature_flag_version", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("trace_id", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("route_decision_id"),
    )
    for name, columns in (
        ("ix_query_route_decision_tenant_id", ["tenant_id"]),
        ("ix_query_route_decision_workspace_id", ["workspace_id"]),
        ("ix_query_route_decision_subject_id", ["subject_id"]),
        ("ix_query_route_decision_scenario", ["scenario"]),
        ("ix_query_route_decision_run_id", ["run_id"]),
        ("ix_query_route_decision_trace_id", ["trace_id"]),
        (
            "ix_query_route_decision_scope_created",
            ["tenant_id", "workspace_id", "scenario", "created_at"],
        ),
    ):
        op.create_index(name, "query_route_decision", columns)


def downgrade() -> None:
    op.drop_table("query_route_decision")
    op.drop_table("shadow_evaluation")
    op.drop_table("sqlbot_session_binding")
