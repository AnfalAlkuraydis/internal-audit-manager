"""Migrations use the explicitly supplied connection; no credentials or .env."""
from alembic import context
from backend.database.tables import metadata

connection = context.config.attributes.get("connection")
# Reuse the connection from database/migrate.py rather than opening a second database.
if connection is None:
    raise RuntimeError("Run migrations with python -m scripts.prepare_data.")
context.configure(connection=connection, target_metadata=metadata, compare_type=True)
with context.begin_transaction():
    context.run_migrations()
