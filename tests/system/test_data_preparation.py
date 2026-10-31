"""Whole Phase 2 data setup; this is not an end-to-end audit test."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import sqlalchemy as sa
from backend.database.connection import create_database
from backend.database.repository import read_bundle, read_catalog
from backend.database.schemas import Evidence, Entity
from backend.database import tables as t

ROOT = Path(__file__).resolve().parents[2]

class DataPreparationTests(unittest.TestCase):
    def test_fresh_setup_and_repeat_via_actual_command(self):
        """The documented CLI creates a migrated, seeded database and safely repeats."""
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "nested" / "audit.sqlite"
            cmd = [sys.executable, "-m", "scripts.prepare_data", "--database", str(db)]
            for _ in range(2):
                result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
            engine = create_database(db)
            try:
                with engine.connect() as connection:
                    counts = {name: connection.scalar(sa.select(sa.func.count()).select_from(table))
                              for name, table in (("policies", t.policies), ("controls", t.controls),
                                  ("entities", t.entities), ("evidence", t.evidence))}
                    dataset_ids = set(connection.execute(sa.select(t.datasets.c.id)).scalars())
                self.assertEqual(counts, {"policies": 3, "controls": 9, "entities": 24, "evidence": 71})
                self.assertEqual(dataset_ids, {"digital-risk-dev.v1"})
                self.observations = counts
            finally:
                engine.dispose()

    def test_answer_keys_cover_data_without_runtime_labels(self):
        """Separate labels cover every control/entity pair; no expected outcome enters runtime data."""
        catalog = read_catalog(ROOT / "data/catalog.json")
        counts = {}
        for split in ("development", "held_out"):
            bundle = read_bundle(ROOT / f"data/{split}/dataset.json")
            key = json.loads((ROOT / f"evaluation/ground_truth/{split}.json").read_text())
            expected_pairs = {(c.id, e.id) for c in catalog.controls
                              for e in bundle.entities if c.entity_kind == e.kind}
            labels = key["labels"]
            self.assertEqual({(r["control_id"], r["entity_id"]) for r in labels}, expected_pairs)
            self.assertEqual(len(labels), len(expected_pairs))
            self.assertEqual(key["dataset_id"], bundle.dataset.id)
            evidence_ids = {e.id for e in bundle.evidence}
            for row in labels:
                self.assertTrue(set(row["evidence_ids"]) <= evidence_ids)
            serialized = bundle.model_dump_json()
            self.assertNotIn("expected_outcome", serialized)
            self.assertNotIn("rationale", serialized)
            counts[split] = len(labels)
        self.assertEqual(counts, {"development": 72, "held_out": 36})
        self.observations = {"label_coverage_only": counts, "control_correctness": "NOT RUN"}

    def test_followup_evidence_is_withheld_and_history_preserved(self):
        """Future replies reveal late approval and new remediation evidence without rewriting history."""
        initial = read_bundle(ROOT / "data/development/dataset.json")
        followup = json.loads((ROOT / "tests/fixtures/followup_messages.json").read_text())
        messages = followup["messages"]
        initial_ids = {e.id for e in initial.evidence}
        reply = Evidence.model_validate(messages[0]["evidence"][0])
        self.assertNotIn(reply.id, initial_ids)
        project = next(e for e in initial.entities if e.id == reply.entity_id)
        self.assertEqual(project.facts["deployed_on"], "2026-03-20")
        self.assertEqual(reply.facts["approved_on"], "2026-03-22")
        implementation = messages[2]
        replacement = Entity.model_validate(implementation["entities"][0])
        self.assertNotIn(replacement.id, {e.id for e in initial.entities})
        for row in implementation["evidence"]:
            parsed = Evidence.model_validate(row)
            self.assertEqual(parsed.entity_id, replacement.id)
            self.assertNotIn(parsed.id, initial_ids)
        self.assertEqual(implementation["verification_period"],
                         {"period_start": "2026-09-01", "period_end": "2026-09-30"})
