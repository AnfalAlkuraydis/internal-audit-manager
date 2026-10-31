"""Freeze Phase 3 storage and protect original evidence and calculated history."""
from alembic import op
import sqlalchemy as sa
metadata = sa.MetaData()
# Existing tables are declared only to resolve new foreign keys, not recreated.
for name in ("engagements", "entities", "controls"):
    sa.Table(name, metadata, sa.Column("id", sa.String, primary_key=True))

# Phase 3 proposals and calculated artifacts have separate, append-only histories.
proposals = sa.Table("proposals", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("engagement_id", sa.String, sa.ForeignKey("engagements.id"), nullable=False, index=True),
    sa.Column("kind", sa.String, nullable=False),
    sa.Column("business_key", sa.String, nullable=False),
    sa.UniqueConstraint("engagement_id", "kind", "business_key", name="proposal_business_key"),
    sa.CheckConstraint("kind IN ('plan','finding','escalation','closure')", name="proposal_kind"))
proposal_versions = sa.Table("proposal_versions", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("proposal_id", sa.String, sa.ForeignKey("proposals.id"), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("document", sa.JSON, nullable=False),
    sa.Column("created_by", sa.String, nullable=False),
    sa.Column("created_at", sa.String, nullable=False),
    sa.UniqueConstraint("proposal_id", "version", name="proposal_version"))
review_decisions = sa.Table("review_decisions", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("version_id", sa.String, sa.ForeignKey("proposal_versions.id"), nullable=False, unique=True),
    sa.Column("decision", sa.String, nullable=False),
    sa.Column("reviewer_id", sa.String, nullable=False),
    sa.Column("reviewer_role", sa.String, nullable=False),
    sa.Column("reason", sa.String, nullable=False),
    sa.Column("created_at", sa.String, nullable=False),
    sa.CheckConstraint("decision IN ('approved','rejected','changes_requested')", name="review_decision"),
    sa.CheckConstraint("reviewer_role IN ('auditor','reviewer')", name="human_reviewer"))
# Each artifact contains a frozen population, evidence selection or calculated run.
artifacts = sa.Table("artifacts", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("engagement_id", sa.String, sa.ForeignKey("engagements.id"), nullable=False, index=True),
    sa.Column("kind", sa.String, nullable=False),
    sa.Column("digest", sa.String(64), nullable=False, unique=True),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("created_at", sa.String, nullable=False),
    sa.CheckConstraint("kind IN ('population','evidence','run')", name="artifact_kind"))
test_results = sa.Table("test_results", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("run_id", sa.String, sa.ForeignKey("artifacts.id"), nullable=False, index=True),
    sa.Column("entity_id", sa.String, sa.ForeignKey("entities.id"), nullable=False),
    sa.Column("control_id", sa.String, sa.ForeignKey("controls.id"), nullable=False),
    sa.Column("outcome", sa.String, nullable=False),
    sa.Column("reason", sa.String, nullable=False),
    sa.Column("evidence_ids", sa.JSON, nullable=False),
    sa.UniqueConstraint("run_id", "entity_id", name="run_member"),
    sa.CheckConstraint("outcome IN ('PASS','FAIL','MISSING_EVIDENCE','CONTRADICTORY_EVIDENCE','ERROR','NOT_APPLICABLE')", name="test_outcome"))
evidence_requests = sa.Table("evidence_requests", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("engagement_id", sa.String, sa.ForeignKey("engagements.id"), nullable=False),
    sa.Column("business_key", sa.String, nullable=False, unique=True),
    sa.Column("document", sa.JSON, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("proposal_id", sa.String, sa.ForeignKey("proposals.id")),
    sa.Column("created_at", sa.String, nullable=False),
    sa.CheckConstraint("status IN ('queued','waiting_for_approval')", name="request_status"))
action_plans = sa.Table("action_plans", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("finding_id", sa.String, sa.ForeignKey("proposals.id"), nullable=False),
    sa.Column("document", sa.JSON, nullable=False),
    sa.Column("recorded_by", sa.String, nullable=False),
    sa.Column("created_at", sa.String, nullable=False))
# A caller key cannot be reused with different arguments or a different tool.
action_receipts = sa.Table("action_receipts", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("actor_id", sa.String, nullable=False),
    sa.Column("operation_id", sa.String, nullable=False),
    sa.Column("input_digest", sa.String, nullable=False),
    sa.Column("result", sa.JSON, nullable=False),
    sa.UniqueConstraint("actor_id", "operation_id", name="actor_operation"))
audit_events = sa.Table("audit_events", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("engagement_id", sa.String, sa.ForeignKey("engagements.id"), nullable=False),
    sa.Column("actor_id", sa.String, nullable=False),
    sa.Column("actor_role", sa.String, nullable=False),
    sa.Column("event", sa.String, nullable=False),
    sa.Column("record_id", sa.String, nullable=False),
    sa.Column("created_at", sa.String, nullable=False))

revision = "0002_execution_reviews"
down_revision = "0001_audit_data"
branch_labels = None
depends_on = None
NEW_TABLES = ("proposals", "proposal_versions", "review_decisions", "artifacts",
              "test_results", "evidence_requests", "action_plans", "action_receipts", "audit_events")
IMMUTABLE = ("evidence", "proposal_versions", "review_decisions", "artifacts",
             "test_results", "action_plans", "action_receipts", "audit_events")

def upgrade():
    """Add execution/review tables and reject updates/deletes of immutable records."""
    metadata.create_all(op.get_bind(), tables=[metadata.tables[name] for name in NEW_TABLES])
    for table in IMMUTABLE:
        for action in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} "
                       "BEGIN SELECT RAISE(ABORT, 'immutable_audit_record'); END")

def downgrade():
    """Remove Phase 3 structures; explicit rollback discards their recorded history."""
    for table in IMMUTABLE:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS protect_{table}_{action}")
    metadata.drop_all(op.get_bind(), tables=[metadata.tables[name] for name in reversed(NEW_TABLES)])
