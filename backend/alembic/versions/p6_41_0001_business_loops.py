"""P6 4.1 alert, report and metric governance closed loops."""

from alembic import op

from app.business_loop.models import P6_TABLES

revision = "p6_41_0001"
down_revision = "integration_41_merge_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in P6_TABLES:
        table.create(bind, checkfirst=False)
    if bind.dialect.name == "postgresql":
        op.execute("""
        CREATE OR REPLACE FUNCTION p6_reject_immutable_report_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF TG_TABLE_NAME = 'p6_report_evidence_snapshot' THEN
            RAISE EXCEPTION 'report evidence snapshots are immutable';
          END IF;
          IF OLD.status = 'PUBLISHED' THEN
            RAISE EXCEPTION 'published report versions are immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)
        op.execute("CREATE TRIGGER p6_report_version_immutable BEFORE UPDATE OR DELETE ON p6_report_version FOR EACH ROW EXECUTE FUNCTION p6_reject_immutable_report_mutation()")
        op.execute("CREATE TRIGGER p6_report_snapshot_immutable BEFORE UPDATE OR DELETE ON p6_report_evidence_snapshot FOR EACH ROW EXECUTE FUNCTION p6_reject_immutable_report_mutation()")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS p6_report_snapshot_immutable ON p6_report_evidence_snapshot")
        op.execute("DROP TRIGGER IF EXISTS p6_report_version_immutable ON p6_report_version")
        op.execute("DROP FUNCTION IF EXISTS p6_reject_immutable_report_mutation()")
    for table in reversed(P6_TABLES):
        table.drop(bind, checkfirst=True)
