"""Add durable agent and email state without changing original evidence history."""
from alembic import op
import sqlalchemy as sa
metadata=sa.MetaData()
for name in ("engagements","datasets","controls","artifacts","evidence_requests","proposals","proposal_versions"):
    sa.Table(name,metadata,sa.Column("id",sa.String,primary_key=True))

# Phase 4: durable single-agent sessions and event-driven simulated communication.
agent_sessions = sa.Table("agent_sessions", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("engagement_id", sa.String, sa.ForeignKey("engagements.id"), unique=True),
    sa.Column("dataset_id", sa.String, sa.ForeignKey("datasets.id"), nullable=False),
    sa.Column("assignment", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("wake_version", sa.Integer, nullable=False),
    sa.Column("handled_version", sa.Integer, nullable=False),
    sa.Column("last_business_event", sa.String, nullable=False),
    sa.Column("lease_owner", sa.String),
    sa.Column("lease_until", sa.String),
    sa.Column("error_code", sa.String),
    sa.Column("updated_at", sa.String, nullable=False))
agent_inferences = sa.Table("agent_inferences", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("session_id", sa.String, sa.ForeignKey("agent_sessions.id"), nullable=False),
    sa.Column("turn_key", sa.String, nullable=False),
    sa.Column("request_digest", sa.String, nullable=False),
    sa.Column("response", sa.JSON, nullable=False),
    sa.Column("offered_tools", sa.JSON, nullable=False),
    sa.Column("created_at", sa.String, nullable=False),
    sa.UniqueConstraint("session_id", "turn_key", name="session_inference_turn"))
agent_calls = sa.Table("agent_calls", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("session_id", sa.String, sa.ForeignKey("agent_sessions.id"), nullable=False),
    sa.Column("call_id", sa.String, nullable=False),
    sa.Column("tool", sa.String, nullable=False),
    sa.Column("arguments", sa.JSON, nullable=False),
    sa.Column("result", sa.JSON, nullable=False),
    sa.Column("success", sa.Boolean, nullable=False),
    sa.Column("schema_valid", sa.Boolean, nullable=False),
    sa.Column("duration_ms", sa.Float, nullable=False),
    sa.Column("created_at", sa.String, nullable=False),
    sa.UniqueConstraint("session_id", "call_id", name="session_tool_call"))
work_items = sa.Table("work_items", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("engagement_id", sa.String, sa.ForeignKey("engagements.id"), nullable=False),
    sa.Column("control_id", sa.String, sa.ForeignKey("controls.id"), nullable=False),
    sa.Column("purpose", sa.String, nullable=False),
    sa.Column("plan_version_id", sa.String, sa.ForeignKey("proposal_versions.id"), nullable=False),
    sa.Column("finding_id", sa.String),
    sa.Column("state", sa.String, nullable=False),
    sa.Column("latest_run_id", sa.String, sa.ForeignKey("artifacts.id")),
    sa.Column("updated_at", sa.String, nullable=False))
activity = sa.Table("activity", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("event_key", sa.String, nullable=False, unique=True),
    sa.Column("session_id", sa.String, sa.ForeignKey("agent_sessions.id")),
    sa.Column("engagement_id", sa.String, sa.ForeignKey("engagements.id")),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("label", sa.String, nullable=False),
    sa.Column("record_type", sa.String),
    sa.Column("record_id", sa.String),
    sa.Column("details", sa.JSON, nullable=False),
    sa.Column("created_at", sa.String, nullable=False))
mail_followups = sa.Table("mail_followups", metadata,
    sa.Column("request_id", sa.String, sa.ForeignKey("evidence_requests.id"), primary_key=True),
    sa.Column("due_at", sa.String, nullable=False),
    sa.Column("interval_days", sa.Integer, nullable=False),
    sa.Column("next_reminder_at", sa.String, nullable=False),
    sa.Column("reminder_count", sa.Integer, nullable=False),
    sa.Column("state", sa.String, nullable=False),
    sa.Column("escalation_proposal_id", sa.String, sa.ForeignKey("proposals.id")),
    sa.Column("updated_at", sa.String, nullable=False))
mail_outbox = sa.Table("mail_outbox", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("request_id", sa.String, sa.ForeignKey("evidence_requests.id"), nullable=False),
    sa.Column("kind", sa.String, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("message_id", sa.String, nullable=False, unique=True),
    sa.Column("review_version_id", sa.String, sa.ForeignKey("proposal_versions.id")),
    sa.Column("envelope", sa.JSON, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False),
    sa.Column("error_code", sa.String),
    sa.Column("created_at", sa.String, nullable=False),
    sa.UniqueConstraint("request_id", "kind", "ordinal", name="request_mail_action"))
simulated_deliveries = sa.Table("simulated_deliveries", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("outbox_id", sa.String, sa.ForeignKey("mail_outbox.id"), nullable=False, unique=True),
    sa.Column("message_id", sa.String, nullable=False, unique=True),
    sa.Column("envelope", sa.JSON, nullable=False),
    sa.Column("delivered_at", sa.String, nullable=False))
mail_inbox = sa.Table("mail_inbox", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("request_id", sa.String, sa.ForeignKey("evidence_requests.id")),
    sa.Column("digest", sa.String, nullable=False),
    sa.Column("sender", sa.String, nullable=False),
    sa.Column("in_reply_to", sa.String, nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("validation_code", sa.String, nullable=False),
    sa.Column("received_at", sa.String, nullable=False))

revision = "0003_agent_followups"
down_revision = "0002_execution_reviews"
branch_labels = None
depends_on = None
NEW = ("agent_sessions","agent_inferences","agent_calls","work_items","activity",
       "mail_followups","mail_outbox","simulated_deliveries","mail_inbox")
FROZEN = ("agent_inferences","agent_calls","activity","simulated_deliveries","mail_inbox")

def upgrade():
    """Expand request lifecycle and add restart-safe orchestration/communication records."""
    with op.batch_alter_table("evidence_requests") as batch:
        batch.drop_constraint("request_status", type_="check")
        batch.create_check_constraint("request_status",
            "status IN ('queued','waiting_for_approval','sent','received','resolved','cancelled')")
    metadata.create_all(op.get_bind(), tables=[metadata.tables[name] for name in NEW])
    for table in FROZEN:
        for action in ("UPDATE","DELETE"):
            op.execute(f"CREATE TRIGGER protect_{table}_{action.lower()} BEFORE {action} ON {table} "
                       "BEGIN SELECT RAISE(ABORT, 'immutable_audit_record'); END")

def downgrade():
    """Remove Phase 4 state only; lifecycle rollback requires compatible request statuses."""
    for table in FROZEN:
        for action in ("update","delete"):
            op.execute(f"DROP TRIGGER IF EXISTS protect_{table}_{action}")
    metadata.drop_all(op.get_bind(), tables=[metadata.tables[name] for name in reversed(NEW)])
    with op.batch_alter_table("evidence_requests") as batch:
        batch.drop_constraint("request_status", type_="check")
        batch.create_check_constraint("request_status", "status IN ('queued','waiting_for_approval')")
