"""Small data access layer; no control execution or LLM decisions."""
import hashlib
import json
from pathlib import Path
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from backend.database import tables as t
from backend.database.schemas import Catalog, SeedBundle, Engagement

class DataConflict(ValueError):
    """An existing stable ID has different content; never overwrite history."""

def fingerprint(value: dict) -> str:
    """Return a stable SHA-256 content fingerprint, ignoring dictionary key order.

    List order is preserved here; callers sort lists when their order has no
    meaning. This detects content differences, not source authenticity.
    """
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def read_catalog(path: Path) -> Catalog:
    """Read policy/control definitions and reject malformed or inconsistent JSON."""
    return Catalog.model_validate_json(path.read_text(encoding="utf-8"))

def read_bundle(path: Path) -> SeedBundle:
    """Read one dataset's population and evidence, validating their references."""
    return SeedBundle.model_validate_json(path.read_text(encoding="utf-8"))

def insert_unchanged(connection, table, values):
    """Insert a new stable ID, returning True; return False for an identical row.

    Raise DataConflict if the ID exists with different content. The caller owns
    the transaction so a conflict can roll back the entire import.
    """
    existing = connection.execute(sa.select(table).where(table.c.id == values["id"])).mappings().first()
    if existing is None:
        connection.execute(table.insert().values(**values))
        return True
    if dict(existing) != values:
        raise DataConflict(f"Existing {table.name} ID has different content.")
    return False

def load_seed(engine: Engine, catalog: Catalog, bundle: SeedBundle) -> dict[str, int]:
    """Import validated catalog and initial evidence together, or roll everything back.

    Return newly inserted counts by category; identical repeats return zeros.
    Unknown/unauthorized sources raise ValueError and changed IDs raise
    DataConflict. Answer keys and future email fixtures are never read.
    """
    source_map = {source.id: source for source in catalog.sources}
    if any(item.source_id not in source_map for item in bundle.entities):
        raise ValueError("Unknown population source.")
    for item in bundle.evidence:
        if item.source_id not in source_map or item.kind not in source_map[item.source_id].allowed_kinds:
            raise ValueError("Evidence source is not authorized for that evidence kind.")
    inserted = {"catalog": 0, "datasets": 0, "entities": 0, "evidence": 0}
    # One transaction prevents a failed import from leaving half a dataset.
    with engine.begin() as connection:
        for table, records in ((t.sources, catalog.sources), (t.policies, catalog.policies),
                               (t.controls, catalog.controls), (t.procedures, catalog.procedures)):
            for item in records:
                inserted["catalog"] += insert_unchanged(connection, table, item.model_dump())
        dataset = bundle.dataset.model_dump()
        snapshot = bundle.model_dump(mode="json")
        # Record ordering is presentation, not a change to the immutable seed snapshot.
        snapshot["entities"].sort(key=lambda item: item["id"])
        snapshot["evidence"].sort(key=lambda item: item["id"])
        dataset["fingerprint"] = fingerprint(snapshot)
        inserted["datasets"] += insert_unchanged(connection, t.datasets, dataset)
        for item in bundle.entities:
            inserted["entities"] += insert_unchanged(
                connection, t.entities, {**item.model_dump(), "dataset_id": bundle.dataset.id})
        # Older evidence versions are inserted first to satisfy self-referencing foreign keys.
        for item in sorted(bundle.evidence, key=lambda item: item.version):
            row = {**item.model_dump(), "dataset_id": bundle.dataset.id,
                   "fingerprint": fingerprint(item.model_dump(mode="json"))}
            inserted["evidence"] += insert_unchanged(connection, t.evidence, row)
    return inserted

def create_engagement(engine: Engine, engagement: Engagement) -> bool:
    """Save an audit assignment whose department matches its existing dataset.

    Return True for a new assignment or False for an identical repeat. This
    records scope only; it does not approve a plan or start an audit.
    """
    with engine.begin() as connection:
        dataset = connection.execute(sa.select(t.datasets).where(
            t.datasets.c.id == engagement.dataset_id)).mappings().first()
        if dataset is None or dataset["department"] != engagement.department:
            raise ValueError("Engagement does not match its dataset department.")
        return insert_unchanged(connection, t.engagements, engagement.model_dump())

def eligible_population(engine: Engine, engagement_id: str, kind: str) -> list[dict]:
    """Return all in-scope records of one kind, sorted by stable ID.

    Active intervals overlap the audit period inclusively; a missing active end
    means still active. Empty scope returns []; unknown IDs/kinds raise ValueError.
    """
    if kind not in {"project", "privileged_account", "device"}:
        raise ValueError("Unknown population kind.")
    with engine.connect() as connection:
        engagement = connection.execute(sa.select(t.engagements).where(
            t.engagements.c.id == engagement_id)).mappings().first()
        if engagement is None:
            raise ValueError("Unknown engagement.")
        # Inclusive dates: project intervals are a single deployment day.
        rows = connection.execute(sa.select(t.entities).where(
            t.entities.c.dataset_id == engagement["dataset_id"],
            t.entities.c.kind == kind,
            t.entities.c.active_from <= engagement["period_end"],
            sa.or_(t.entities.c.active_to.is_(None),
                   t.entities.c.active_to >= engagement["period_start"]),
        ).order_by(t.entities.c.id)).mappings()
        return [dict(row) for row in rows]

def applicable_controls(engine: Engine, engagement_id: str) -> list[dict]:
    """Find controls whose department and policy dates overlap an assignment.

    This returns candidate controls, not test results. The future testing engine
    must bind each test to the policy version effective on the tested date.
    """
    with engine.connect() as connection:
        engagement = connection.execute(sa.select(t.engagements).where(
            t.engagements.c.id == engagement_id)).mappings().first()
        if engagement is None:
            raise ValueError("Unknown engagement.")
        rows = connection.execute(sa.select(t.controls).join(t.policies).where(
            t.policies.c.department == engagement["department"],
            t.policies.c.effective_from <= engagement["period_end"],
            sa.or_(t.policies.c.effective_to.is_(None),
                   t.policies.c.effective_to >= engagement["period_start"]),
        ).order_by(t.controls.c.id)).mappings()
        return [dict(row) for row in rows]
