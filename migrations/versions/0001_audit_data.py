"""Initial immutable schema snapshot; do not import evolving runtime table definitions."""
from alembic import op
import sqlalchemy as sa

metadata = sa.MetaData()
sources = sa.Table("sources", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("system", sa.String, nullable=False),
    sa.Column("authority", sa.String, nullable=False),
    sa.Column("allowed_kinds", sa.JSON, nullable=False),
    sa.CheckConstraint("authority IN ('original', 'secondary')", name="source_authority"))
policies = sa.Table("policies", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("title", sa.String, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("department", sa.String, nullable=False),
    sa.Column("effective_from", sa.Date, nullable=False),
    sa.Column("effective_to", sa.Date),
    sa.Column("text", sa.String, nullable=False),
    sa.CheckConstraint("version > 0", name="policy_version"),
    sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="policy_dates"))
controls = sa.Table("controls", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("policy_id", sa.String, sa.ForeignKey("policies.id"), nullable=False),
    sa.Column("title", sa.String, nullable=False),
    sa.Column("entity_kind", sa.String, nullable=False),
    sa.Column("requirement", sa.String, nullable=False),
    sa.CheckConstraint("entity_kind IN ('project', 'privileged_account', 'device')", name="control_kind"))
procedures = sa.Table("procedures", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("control_id", sa.String, sa.ForeignKey("controls.id"), nullable=False, unique=True),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("instructions", sa.String, nullable=False),
    sa.Column("rule", sa.JSON, nullable=False),
    sa.CheckConstraint("version > 0", name="procedure_version"))
datasets = sa.Table("datasets", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("split", sa.String, nullable=False),
    sa.Column("department", sa.String, nullable=False),
    sa.Column("description", sa.String, nullable=False),
    sa.Column("fingerprint", sa.String(64), nullable=False),
    sa.CheckConstraint("split IN ('development', 'held_out')", name="dataset_split"),
    sa.CheckConstraint("version > 0", name="dataset_version"))
entities = sa.Table("entities", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("dataset_id", sa.String, sa.ForeignKey("datasets.id"), nullable=False, index=True),
    sa.Column("source_id", sa.String, sa.ForeignKey("sources.id"), nullable=False),
    sa.Column("kind", sa.String, nullable=False),
    sa.Column("name", sa.String, nullable=False),
    sa.Column("active_from", sa.Date, nullable=False),
    sa.Column("active_to", sa.Date),
    sa.Column("facts", sa.JSON, nullable=False),
    sa.UniqueConstraint("id", "dataset_id", name="entity_dataset"),
    sa.CheckConstraint("active_to IS NULL OR active_to >= active_from", name="entity_dates"),
    sa.CheckConstraint("kind IN ('project', 'privileged_account', 'device')", name="entity_kind"))
evidence = sa.Table("evidence", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("dataset_id", sa.String, sa.ForeignKey("datasets.id"), nullable=False, index=True),
    sa.Column("entity_id", sa.String, nullable=False),
    sa.Column("source_id", sa.String, sa.ForeignKey("sources.id"), nullable=False),
    sa.Column("source_record_id", sa.String, nullable=False),
    sa.Column("kind", sa.String, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("observed_on", sa.Date, nullable=False),
    sa.Column("captured_on", sa.Date, nullable=False),
    sa.Column("supersedes_id", sa.String),
    sa.Column("facts", sa.JSON, nullable=False),
    sa.Column("fingerprint", sa.String(64), nullable=False),
    sa.UniqueConstraint("id", "dataset_id", name="evidence_dataset"),
    sa.UniqueConstraint("dataset_id", "source_id", "source_record_id", "version", name="source_version"),
    sa.ForeignKeyConstraint(["entity_id", "dataset_id"], ["entities.id", "entities.dataset_id"]),
    sa.ForeignKeyConstraint(["supersedes_id", "dataset_id"], ["evidence.id", "evidence.dataset_id"]),
    sa.CheckConstraint("version > 0", name="evidence_version"),
    sa.CheckConstraint("captured_on >= observed_on", name="evidence_dates"))
engagements = sa.Table("engagements", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("dataset_id", sa.String, sa.ForeignKey("datasets.id"), nullable=False),
    sa.Column("department", sa.String, nullable=False),
    sa.Column("period_start", sa.Date, nullable=False),
    sa.Column("period_end", sa.Date, nullable=False),
    sa.CheckConstraint("period_end >= period_start", name="engagement_dates"))

revision = "0001_audit_data"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    """Create the initial schema from this frozen migration snapshot."""
    metadata.create_all(op.get_bind())

def downgrade():
    """Remove tables defined by this revision; a rollback also removes their data."""
    metadata.drop_all(op.get_bind())
