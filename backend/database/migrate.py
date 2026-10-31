"""Apply versioned database structure changes using the caller's SQLite engine."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]

def migrate(engine: Engine, revision: str = "head") -> None:
    """Upgrade to the requested Alembic revision; 'head' means the latest version.

    This changes table structure, not synthetic data. Passing the connection
    explicitly keeps migration setup independent of credentials and .env files.
    """
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with engine.begin() as connection:
        # env.py reuses this connection, including its SQLite safeguards.
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
