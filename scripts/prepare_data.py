"""Create/migrate an explicit local database and load one synthetic partition."""
import argparse
from pathlib import Path
import os
from dotenv import load_dotenv
from backend.database.connection import create_database
from backend.database.migrate import migrate
from backend.database.repository import load_seed, read_catalog, read_bundle

ROOT = Path(__file__).resolve().parents[1]

def main():
    """Parse setup options, validate inputs, migrate storage and import one seed partition."""
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path,
                        default=Path(os.environ.get("AUDIT_DATABASE_PATH", "var/audit.sqlite")))
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/development/dataset.json")
    args = parser.parse_args()
    # Validate complete source files before touching the database.
    catalog = read_catalog(ROOT / "data/catalog.json")
    bundle = read_bundle(args.dataset)
    args.database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_database(args.database)
    try:
        migrate(engine)
        counts = load_seed(engine, catalog, bundle)
        print({"dataset_id": bundle.dataset.id, "split": bundle.dataset.split, "inserted": counts})
    finally:
        engine.dispose()

if __name__ == "__main__":
    main()
