"""Verify schema migrations, repeatable loading and scope queries in temporary databases."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from backend.database import tables as t
from backend.database.connection import create_database
from backend.database.migrate import migrate
from backend.database.repository import (
    DataConflict, read_catalog, read_bundle, load_seed, create_engagement,
    eligible_population, applicable_controls, fingerprint,
)
from backend.database.schemas import SeedBundle, Engagement

ROOT = Path(__file__).resolve().parents[2]

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        """Prepare isolated fixtures and register temporary resource cleanup."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = create_database(Path(self.temp.name) / "test.sqlite")
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.catalog = read_catalog(ROOT / "data/catalog.json")
        self.bundle = read_bundle(ROOT / "data/development/dataset.json")

    def load(self, bundle=None):
        """Import the selected fixture through the real transactional loader."""
        return load_seed(self.engine, self.catalog, bundle or self.bundle)

    def audit(self, id="AUDIT-DEV", dataset_id="digital-risk-dev.v1",
              start="2026-01-01", end="2026-08-31"):
        """Save an engagement fixture for date and partition query tests."""
        create_engagement(self.engine, Engagement(
            id=id, dataset_id=dataset_id, department="Digital Risk",
            period_start=start, period_end=end))
        return id

    def test_migration_matches_metadata_and_is_repeatable(self):
        """A fresh Alembic migration matches the application schema; rerunning changes nothing."""
        migrate(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)
            self.assertEqual(connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar(),
                             "0003_agent_followups")
            self.assertEqual(compare_metadata(MigrationContext.configure(connection), t.metadata), [])

    def test_seed_repeats_without_duplicates_or_history_changes(self):
        """Repeated loads insert no duplicates and retain every original evidence fingerprint."""
        first = self.load()
        self.assertEqual(first, {"catalog": 28, "datasets": 1, "entities": 24, "evidence": 71})
        self.assertEqual(self.load(), {"catalog": 0, "datasets": 0, "entities": 0, "evidence": 0})
        with self.engine.connect() as connection:
            rows = connection.execute(sa.select(t.evidence)).mappings().all()
        self.assertEqual(len(rows), 71)
        source_item = self.bundle.evidence[0]
        self.assertEqual(rows[0]["fingerprint"], fingerprint(source_item.model_dump(mode="json")))

    def test_changed_seed_rolls_back_without_overwriting_evidence(self):
        """Conflicting immutable content is rejected and the transaction leaves original rows intact."""
        self.load()
        data = self.bundle.model_dump(mode="json")
        data["evidence"][0]["facts"]["assessed_on"] = "2026-01-02"
        with self.assertRaises(DataConflict):
            self.load(SeedBundle.model_validate(data))
        with self.engine.connect() as connection:
            original = connection.execute(sa.select(t.evidence.c.facts).where(
                t.evidence.c.id == self.bundle.evidence[0].id)).scalar_one()
        self.assertEqual(original, self.bundle.evidence[0].facts)

    def test_invalid_source_is_rejected_before_loading(self):
        """Unknown sources and a secondary source posing as original approval are rejected."""
        for invalid_source in ("UNKNOWN", "compass"):
            data = self.bundle.model_dump(mode="json")
            next(e for e in data["evidence"] if e["kind"] == "project_approval")["source_id"] = invalid_source
            with self.subTest(source=invalid_source), self.assertRaises(ValueError):
                self.load(SeedBundle.model_validate(data))
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(sa.select(sa.func.count()).select_from(t.datasets)), 0)

    def test_database_foreign_keys_reject_orphans_and_cross_dataset_links(self):
        """SQLite itself prevents orphan references and cross-partition evidence relationships."""
        self.load()
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(t.controls.insert().values(
                id="BAD", policy_id="MISSING", title="Bad", entity_kind="project", requirement="Bad"))
        held = read_bundle(ROOT / "data/held_out/dataset.json")
        self.load(held)
        data = self.bundle.evidence[0].model_dump()
        data.update(id="CROSS-LINK", dataset_id=held.dataset.id, fingerprint="0" * 64)
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(t.evidence.insert().values(**data))

    def test_period_boundaries_and_population_scope(self):
        """First and last audit days are included; dates outside scope are excluded."""
        self.load()
        main = self.audit()
        for kind in ("project", "privileged_account", "device"):
            self.assertEqual(len(eligible_population(self.engine, main, kind)), 8)
        self.assertEqual(len(applicable_controls(self.engine, main)), 9)
        first = self.audit("FIRST", start="2026-01-01", end="2026-01-01")
        last = self.audit("LAST", start="2026-08-31", end="2026-08-31")
        outside = self.audit("OUTSIDE", start="2025-12-31", end="2025-12-31")
        self.assertEqual([r["id"] for r in eligible_population(self.engine, first, "project")], ["PRJ-001"])
        self.assertEqual([r["id"] for r in eligible_population(self.engine, last, "project")], ["PRJ-008"])
        self.assertEqual(eligible_population(self.engine, outside, "project"), [])
        self.assertEqual(applicable_controls(self.engine, outside), [])

    def test_new_records_and_intervals_need_no_code_changes(self):
        """Additional configured accounts work, including inclusive active-interval boundaries."""
        data = self.bundle.model_dump(mode="json")
        template = next(e for e in data["entities"] if e["kind"] == "privileged_account")
        examples = [
            ("EXTRA-END-BEFORE", "2025-01-01", "2025-12-31", False),
            ("EXTRA-END-ON-START", "2025-01-01", "2026-01-01", True),
            ("EXTRA-START-ON-END", "2026-08-31", None, True),
            ("EXTRA-START-AFTER", "2026-09-01", None, False)]
        for id, start, end, _ in examples:
            row = deepcopy(template)
            row.update(id=id, active_from=start, active_to=end)
            data["entities"].append(row)
        self.load(SeedBundle.model_validate(data))
        actual = {r["id"] for r in eligible_population(self.engine, self.audit(), "privileged_account")}
        for id, _, _, expected in examples:
            self.assertEqual(id in actual, expected)

    def test_heldout_partition_and_engagements_are_isolated(self):
        """An engagement queries only its selected partition, even with both datasets loaded."""
        self.load()
        held = read_bundle(ROOT / "data/held_out/dataset.json")
        self.load(held)
        dev_audit = self.audit()
        held_audit = self.audit("AUDIT-HELD", held.dataset.id, "2027-02-01", "2027-04-30")
        dev_ids = {r["id"] for r in eligible_population(self.engine, dev_audit, "project")}
        held_ids = {r["id"] for r in eligible_population(self.engine, held_audit, "project")}
        self.assertEqual(len(dev_ids), 8)
        self.assertEqual(len(held_ids), 4)
        self.assertFalse(dev_ids & held_ids)
        self.assertEqual(len(applicable_controls(self.engine, held_audit)), 9)

    def test_invalid_engagements_and_requests(self):
        """Unknown engagements, kinds and mismatched departments fail clearly."""
        self.load()
        with self.assertRaises(ValueError):
            create_engagement(self.engine, Engagement(
                id="BAD", dataset_id=self.bundle.dataset.id, department="Other",
                period_start="2026-01-01", period_end="2026-08-31"))
        with self.assertRaises(ValueError):
            eligible_population(self.engine, "MISSING", "project")
        with self.assertRaises(ValueError):
            eligible_population(self.engine, self.audit(), "unknown")

    def test_catalog_failure_is_atomic(self):
        """A conflicting late catalog row rolls back earlier inserts in the same load."""
        self.load()
        from backend.database.schemas import Catalog
        data = self.catalog.model_dump(mode="json")
        data["sources"].insert(0, {"id": "new-source", "system": "New", "authority": "original",
                                  "allowed_kinds": ["risk_assessment"]})
        data["procedures"][-1]["instructions"] = "Conflicting existing procedure."
        with self.assertRaises(DataConflict):
            load_seed(self.engine, Catalog.model_validate(data), self.bundle)
        with self.engine.connect() as connection:
            self.assertIsNone(connection.execute(sa.select(t.sources).where(
                t.sources.c.id == "new-source")).first())

    def test_evidence_versions_preserve_originals(self):
        """A replacement version coexists with the original and retains its provenance."""
        data = self.bundle.model_dump(mode="json")
        original = data["evidence"][0]
        replacement = deepcopy(original)
        replacement.update(id=original["id"] + ".replacement", version=2,
                           supersedes_id=original["id"])
        data["evidence"].append(replacement)
        self.load(SeedBundle.model_validate(data))
        with self.engine.connect() as connection:
            rows = connection.execute(sa.select(t.evidence).where(
                t.evidence.c.source_record_id == original["source_record_id"])).mappings().all()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["version"] for r in rows}, {1, 2})
        self.assertEqual(rows[0]["facts"], original["facts"])

    def test_reordered_seed_is_the_same_snapshot(self):
        """Changing JSON record order must not change the identity of the same seed snapshot."""
        self.load()
        data = self.bundle.model_dump(mode="json")
        data["entities"].reverse()
        data["evidence"].reverse()
        self.assertEqual(self.load(SeedBundle.model_validate(data)),
                         {"catalog": 0, "datasets": 0, "entities": 0, "evidence": 0})

    def test_empty_dataset_and_unknown_dataset(self):
        """Empty populations are valid; an engagement cannot refer to an absent dataset."""
        data = self.bundle.model_dump(mode="json")
        data.update(entities=[], evidence=[])
        self.load(SeedBundle.model_validate(data))
        audit = self.audit()
        self.assertEqual(eligible_population(self.engine, audit, "project"), [])
        with self.assertRaises(ValueError):
            self.audit("INVALID-DATASET", dataset_id="ABSENT")
