"""Open local SQLite databases and enable the safeguards every connection needs.

An engine manages database connections. Creating it does not apply migrations
or load records; those are separate, explicit setup steps.
"""
from pathlib import Path
import sqlalchemy as sa
from sqlalchemy.engine import Engine, URL

def create_database(path: str | Path) -> Engine:
    """Use a path, not a credential-bearing database URL. No automatic schema writes."""
    path = Path(path).resolve()
    engine = sa.create_engine(URL.create("sqlite", database=str(path)), echo=False)

    @sa.event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        """Enable relationship checks and briefly wait when another writer holds a lock."""
        cursor = connection.cursor()
        # SQLite otherwise accepts references to records that do not exist.
        cursor.execute("PRAGMA foreign_keys=ON")
        # Wait up to five seconds for a lock instead of immediately failing.
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
    return engine
